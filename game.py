"""
Logique du jeu Pili Pili (règles de base, sans cartes Mission).

Ce module ne connaît rien du réseau : il gère uniquement l'état d'une partie
et applique les règles du PDF officiel. Le serveur (app.py) l'utilise et
diffuse l'état aux joueurs.

Règles implémentées :
- 55 cartes numérotées (1 à 55) + 1 Joker.
- On distribue N cartes par joueur (5 par défaut, réglable).
- Paris : chacun annonce combien de plis il pense remporter, dans l'ordre à
  partir du donneur. La SOMME des paris doit être différente du nombre de
  cartes distribuées : seul le dernier parieur est contraint d'ajuster.
- Plis : la plus grande valeur remporte le pli ; le gagnant relance.
  Les couleurs ne comptent pas. Le Joker prend une valeur choisie (0 à 56).
- Pénalités : |pari - plis remportés| Pilis par joueur.
- Fin : dès qu'un joueur atteint 7 Pilis, la partie s'arrête ; le(s)
  joueur(s) avec le moins de Pilis gagne(nt).
"""

import random
import string

DECK_SIZE = 55          # cartes numérotées 1..55
JOKER_MIN = 0           # valeur minimale que le Joker peut prendre
JOKER_MAX = 56          # valeur maximale que le Joker peut prendre
MAX_PILIS = 7           # la partie s'arrête dès qu'un joueur atteint ce total
DEFAULT_HAND = 5        # cartes distribuées par joueur (règles de base)
MIN_HAND = 1
MAX_HAND = 12
MIN_PLAYERS = 2
MAX_PLAYERS = 8

# Alphabet sans caractères ambigus (0/O, 1/I/L) pour les codes de salon.
ROOM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_deck():
    """Retourne un paquet neuf : 55 cartes numérotées + 1 Joker."""
    deck = [{"id": f"n{n}", "kind": "num", "value": n} for n in range(1, DECK_SIZE + 1)]
    deck.append({"id": "joker", "kind": "joker", "value": None})
    return deck


def new_room_code(existing):
    """Génère un code de salon court et lisible, unique parmi `existing`."""
    while True:
        code = "".join(random.choice(ROOM_ALPHABET) for _ in range(4))
        if code not in existing:
            return code


class Player:
    def __init__(self, player_id, name):
        self.id = player_id
        self.name = name
        self.sid = None          # identifiant Socket.IO courant
        self.connected = True
        self.pilis = 0           # score cumulé (on veut le plus bas)
        # État de la manche en cours :
        self.hand = []           # liste de cartes
        self.bet = None          # pari annoncé (None tant que non parié)
        self.tricks = 0          # plis remportés cette manche


class GameError(Exception):
    """Action de jeu invalide ; le message est destiné au joueur."""
    pass


class Game:
    def __init__(self, room_id, cards_per_hand=DEFAULT_HAND):
        self.room_id = room_id
        self.cards_per_hand = int(cards_per_hand)
        self.players = []            # ordre = ordre de jeu (dans le sens horaire)
        self.host_id = None
        self.phase = "lobby"         # lobby | betting | playing | round_end | game_over
        self.dealer_index = 0
        self.turn_index = 0          # index du joueur qui doit agir
        self.current_trick = []      # [{player_id, player_name, value, is_joker}]
        self.round_number = 0
        self.last_trick = None       # dernier pli résolu (pour l'affichage)
        self.round_summary = None    # bilan de fin de manche
        self.winners = []            # ids des vainqueurs (fin de partie)
        self.log = []                # petit journal des événements

    # ------------------------------------------------------------------ #
    # Gestion des joueurs / connexions
    # ------------------------------------------------------------------ #
    def get_player(self, player_id):
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def player_by_sid(self, sid):
        for p in self.players:
            if p.sid == sid:
                return p
        return None

    def add_or_reconnect(self, player_id, name, sid):
        """Ajoute un nouveau joueur ou reconnecte un joueur existant."""
        existing = self.get_player(player_id)
        if existing:
            existing.sid = sid
            existing.connected = True
            if name:
                existing.name = name.strip()[:20]
            return existing

        if self.phase != "lobby":
            raise GameError("La partie a déjà commencé. Impossible de rejoindre.")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("Ce salon est complet.")

        player = Player(player_id, (name or "Joueur").strip()[:20] or "Joueur")
        player.sid = sid
        self.players.append(player)
        if self.host_id is None:
            self.host_id = player.id
        return player

    def mark_disconnected(self, sid):
        p = self.player_by_sid(sid)
        if p:
            p.connected = False
            p.sid = None
        return p

    def _add_log(self, message):
        self.log.append(message)
        self.log = self.log[-8:]

    # ------------------------------------------------------------------ #
    # Démarrage / distribution
    # ------------------------------------------------------------------ #
    def start_game(self, player_id):
        if player_id != self.host_id:
            raise GameError("Seul l'hôte peut lancer la partie.")
        if self.phase != "lobby":
            raise GameError("La partie est déjà lancée.")
        if len(self.players) < MIN_PLAYERS:
            raise GameError("Il faut au moins 2 joueurs pour commencer.")
        if self.cards_per_hand < MIN_HAND:
            raise GameError("Nombre de cartes par joueur invalide.")
        if self.cards_per_hand * len(self.players) > (DECK_SIZE + 1):
            raise GameError("Trop de cartes par joueur pour ce nombre de joueurs.")

        for p in self.players:
            p.pilis = 0
        self.round_number = 0
        self.dealer_index = random.randrange(len(self.players))
        self.winners = []
        self._deal_round()

    def _deal_round(self):
        """Prépare une nouvelle manche : mélange, distribue, ouvre les paris."""
        self.round_number += 1
        deck = make_deck()
        random.shuffle(deck)

        for p in self.players:
            p.hand = []
            p.bet = None
            p.tricks = 0

        # Distribution dans l'ordre à partir du donneur.
        n = len(self.players)
        idx = 0
        for _ in range(self.cards_per_hand):
            for offset in range(n):
                p = self.players[(self.dealer_index + offset) % n]
                p.hand.append(deck[idx])
                idx += 1

        # Tri de la main pour une lecture agréable (esthétique uniquement).
        for p in self.players:
            p.hand.sort(key=lambda c: (c["kind"] != "joker", c["value"] or 0))

        self.current_trick = []
        self.last_trick = None
        self.round_summary = None
        self.trick_leader_index = self.dealer_index
        self.turn_index = self.dealer_index
        self.phase = "betting"
        self._add_log(f"Manche {self.round_number} : {self.cards_per_hand} cartes distribuées.")

    # ------------------------------------------------------------------ #
    # Phase de paris
    # ------------------------------------------------------------------ #
    def legal_bets(self, player):
        """Liste des paris autorisés pour ce joueur à cet instant."""
        h = self.cards_per_hand
        options = list(range(0, h + 1))
        placed = sum(1 for p in self.players if p.bet is not None)
        is_last = placed == len(self.players) - 1
        if is_last:
            others_sum = sum(p.bet for p in self.players if p.bet is not None)
            forbidden = h - others_sum
            if 0 <= forbidden <= h:
                options = [b for b in options if b != forbidden]
        return options

    def place_bet(self, player_id, value):
        if self.phase != "betting":
            raise GameError("Ce n'est pas le moment de parier.")
        player = self.players[self.turn_index]
        if player.id != player_id:
            raise GameError("Ce n'est pas votre tour de parier.")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise GameError("Pari invalide.")
        if value not in self.legal_bets(player):
            raise GameError("Ce pari n'est pas autorisé (la somme des paris ne peut pas égaler le nombre de cartes distribuées).")

        player.bet = value
        self._add_log(f"{player.name} parie {value}.")

        # Tous les joueurs ont-ils parié ?
        if all(p.bet is not None for p in self.players):
            self.phase = "playing"
            self.trick_leader_index = self.dealer_index
            self.turn_index = self.dealer_index
            self.current_trick = []
            self._add_log("Tous les paris sont faits. À vous de jouer !")
        else:
            self.turn_index = (self.turn_index + 1) % len(self.players)

    # ------------------------------------------------------------------ #
    # Phase de jeu (plis)
    # ------------------------------------------------------------------ #
    def play_card(self, player_id, card_id, joker_value=None):
        if self.phase != "playing":
            raise GameError("Ce n'est pas le moment de jouer une carte.")
        player = self.players[self.turn_index]
        if player.id != player_id:
            raise GameError("Ce n'est pas votre tour.")

        card = next((c for c in player.hand if c["id"] == card_id), None)
        if card is None:
            raise GameError("Vous n'avez pas cette carte.")

        if card["kind"] == "joker":
            if joker_value is None:
                raise GameError("Choisissez une valeur pour le Joker.")
            try:
                joker_value = int(joker_value)
            except (TypeError, ValueError):
                raise GameError("Valeur de Joker invalide.")
            if not (JOKER_MIN <= joker_value <= JOKER_MAX):
                raise GameError(f"Le Joker doit valoir entre {JOKER_MIN} et {JOKER_MAX}.")
            value = joker_value
        else:
            value = card["value"]

        player.hand.remove(card)
        self.current_trick.append({
            "player_id": player.id,
            "player_name": player.name,
            "value": value,
            "is_joker": card["kind"] == "joker",
        })

        if len(self.current_trick) == len(self.players):
            self._resolve_trick()
        else:
            self.turn_index = (self.turn_index + 1) % len(self.players)

    def _resolve_trick(self):
        """Détermine le gagnant du pli. Valeur la plus haute ; égalité =
        la première carte jouée l'emporte (cas limite possible avec le Joker)."""
        best_i = 0
        for i in range(1, len(self.current_trick)):
            if self.current_trick[i]["value"] > self.current_trick[best_i]["value"]:
                best_i = i
        winner_id = self.current_trick[best_i]["player_id"]
        winner = self.get_player(winner_id)
        winner.tricks += 1

        self.last_trick = {
            "cards": list(self.current_trick),
            "winner_id": winner_id,
            "winner_name": winner.name,
        }
        self._add_log(f"{winner.name} remporte le pli.")

        winner_index = self.players.index(winner)
        self.trick_leader_index = winner_index
        self.turn_index = winner_index
        self.current_trick = []

        if all(len(p.hand) == 0 for p in self.players):
            self._resolve_round()

    def _resolve_round(self):
        """Attribue les Pilis de pénalité et vérifie la fin de partie."""
        summary = []
        for p in self.players:
            gap = abs(p.bet - p.tricks)
            p.pilis += gap
            summary.append({
                "player_id": p.id,
                "name": p.name,
                "bet": p.bet,
                "tricks": p.tricks,
                "gained": gap,
                "total": p.pilis,
            })
        self.round_summary = summary

        if any(p.pilis >= MAX_PILIS for p in self.players):
            fewest = min(p.pilis for p in self.players)
            self.winners = [p.id for p in self.players if p.pilis == fewest]
            self.phase = "game_over"
            names = ", ".join(self.get_player(w).name for w in self.winners)
            self._add_log(f"Partie terminée. Vainqueur : {names}.")
        else:
            self.phase = "round_end"
            self._add_log("Fin de la manche. Prêts pour la suivante ?")

    def next_round(self, player_id):
        if self.phase != "round_end":
            raise GameError("La manche n'est pas terminée.")
        if player_id != self.host_id:
            raise GameError("Seul l'hôte peut lancer la manche suivante.")
        self.dealer_index = (self.dealer_index + 1) % len(self.players)
        self._deal_round()

    def restart(self, player_id):
        if player_id != self.host_id:
            raise GameError("Seul l'hôte peut relancer une partie.")
        if self.phase != "game_over":
            raise GameError("La partie n'est pas terminée.")
        self.phase = "lobby"
        self.round_number = 0
        self.winners = []
        for p in self.players:
            p.pilis = 0
            p.hand = []
            p.bet = None
            p.tricks = 0
        self.current_trick = []
        self.last_trick = None
        self.round_summary = None
        self._add_log("Nouvelle partie ! En attente du lancement.")

    # ------------------------------------------------------------------ #
    # Sérialisation de l'état pour un joueur donné
    # ------------------------------------------------------------------ #
    def state_for(self, player_id):
        me = self.get_player(player_id)
        turn_player = self.players[self.turn_index] if self.players else None
        turn_id = turn_player.id if (turn_player and self.phase in ("betting", "playing")) else None

        players_view = []
        for i, p in enumerate(self.players):
            players_view.append({
                "id": p.id,
                "name": p.name,
                "connected": p.connected,
                "pilis": p.pilis,
                "bet": p.bet,                       # visible dès qu'il est annoncé
                "tricks": p.tricks,
                "handCount": len(p.hand),
                "isDealer": i == self.dealer_index and self.phase != "lobby",
                "isTurn": turn_id is not None and p.id == turn_id,
                "isHost": p.id == self.host_id,
                "isYou": p.id == player_id,
            })

        state = {
            "roomId": self.room_id,
            "phase": self.phase,
            "cardsPerHand": self.cards_per_hand,
            "maxPilis": MAX_PILIS,
            "roundNumber": self.round_number,
            "hostId": self.host_id,
            "players": players_view,
            "currentTrick": list(self.current_trick),
            "lastTrick": self.last_trick,
            "turnPlayerId": turn_id,
            "dealerId": self.players[self.dealer_index].id if self.players and self.phase != "lobby" else None,
            "log": list(self.log),
            "you": {
                "id": me.id if me else None,
                "name": me.name if me else None,
                "hand": list(me.hand) if me else [],
                "bet": me.bet if me else None,
                "isHost": bool(me and me.id == self.host_id),
            },
            "yourTurn": turn_id is not None and me is not None and me.id == turn_id,
            "jokerRange": [JOKER_MIN, JOKER_MAX],
        }

        if self.phase == "betting" and state["yourTurn"] and me is not None:
            state["legalBets"] = self.legal_bets(me)

        if self.phase == "round_end":
            state["roundSummary"] = self.round_summary

        if self.phase == "game_over":
            state["roundSummary"] = self.round_summary
            state["winners"] = [
                {"id": w, "name": self.get_player(w).name} for w in self.winners
            ]

        if self.phase == "lobby":
            state["canStart"] = (
                bool(me and me.id == self.host_id) and len(self.players) >= MIN_PLAYERS
            )

        return state
