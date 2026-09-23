"""
Logique du jeu Pili Pili (règles de base + cartes Mission + pierre-feuille-ciseaux).

Ce module ne connaît rien du réseau : il gère uniquement l'état d'une partie
et applique les règles. Le serveur (app.py) l'utilise et diffuse l'état.

Deux nouveautés par rapport à la version de base :
- PIERRE-FEUILLE-CISEAUX : avant la toute première manche, les joueurs
  s'affrontent au pfc ; le gagnant devient le premier donneur (« celui qui
  commence »). En cas d'égalité, on rejoue.
- CARTES MISSION : au début de chaque manche (si activées), on pioche une
  Mission qui modifie les règles de la manche. Seules les Missions qui ont
  du sens en ligne sont incluses (les Missions « physiques » du jeu de
  société — cartes sur le front, décompte de 3 s à voix haute, jeu
  simultané, échange de carte à chaque pli — sont volontairement écartées).
"""

import random

DECK_SIZE = 55
JOKER_MIN = 0
JOKER_MAX = 56
MAX_PILIS = 7
DEFAULT_HAND = 5
MIN_HAND = 1
MAX_HAND = 12
MIN_PLAYERS = 2
MAX_PLAYERS = 8

ROOM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


def make_deck():
    """Retourne un paquet neuf : 55 cartes numérotées + 1 Joker."""
    deck = [{"id": f"n{n}", "kind": "num", "value": n} for n in range(1, DECK_SIZE + 1)]
    deck.append({"id": "joker", "kind": "joker", "value": None})
    return deck


def new_room_code(existing):
    while True:
        code = "".join(random.choice(ROOM_ALPHABET) for _ in range(4))
        if code not in existing:
            return code


# ---------------------------------------------------------------------- #
# Catalogue des Missions
# ---------------------------------------------------------------------- #
# Chaque Mission est décrite par un "template" ; certaines tirent des
# paramètres au hasard au moment de la pioche (numéros maudits, sens du
# cadeau...). `feasible` vérifie qu'elle a du sens pour la config courante.
MISSION_TEMPLATES = [
    {
        "key": "bet_blind",
        "title": "Paris à l'aveugle",
        "desc": "Chacun parie AVANT de voir ses cartes.",
        "flags": {"bet_blind": True},
    },
    {
        "key": "no_bet_0",
        "title": "Zéro interdit",
        "desc": "Interdit d'annoncer un pari de 0.",
        "flags": {"forbid_bet": 0},
    },
    {
        "key": "no_bet_1",
        "title": "Un interdit",
        "desc": "Interdit d'annoncer un pari de 1.",
        "flags": {"forbid_bet": 1},
    },
    {
        "key": "no_copy",
        "title": "Pas de copie",
        "desc": "Interdit de copier le pari du joueur précédent.",
        "flags": {"no_copy": True},
    },
    {
        "key": "inverted",
        "title": "Valeurs inversées",
        "desc": "Tout est inversé : le 1 devient la plus forte, le 55 la plus faible.",
        "expert": True,
        "flags": {"inverted": True},
    },
    {
        "key": "high_or_low",
        "title": "Tout ou rien",
        "desc": "Tu dois toujours jouer ta carte la plus forte ou la plus faible.",
        "flags": {"high_or_low": True},
    },
    {
        "key": "open_hands",
        "title": "Cartes sur table",
        "desc": "Après les paris, toutes les mains sont visibles par tout le monde.",
        "flags": {"open_hands": True},
    },
    {
        "key": "discard",
        "title": "Pari libérateur",
        "desc": "Pari réussi ? Tu défausses autant de Pilis que la valeur de ton pari.",
        "flags": {"discard_on_success": True},
    },
    {
        "key": "first_last",
        "title": "Premier et dernier",
        "desc": "Remporter le premier et/ou le dernier pli coûte 1 Pili.",
        "expert": True,
        "flags": {"first_last_penalty": True},
    },
    {
        "key": "cursed",
        "title": "Numéros maudits",
        "desc": "Remporter un pli contenant un numéro maudit coûte 1 Pili.",
        "flags": {"cursed": True},
    },
    {
        "key": "bonus_card",
        "title": "Carte surprise",
        "desc": "Après les paris, chacun pioche une carte supplémentaire au hasard.",
        "flags": {"bonus_card": True},
    },
    {
        "key": "designate",
        "title": "Fardeau partagé",
        "desc": "Après les paris, désigne un joueur : en fin de manche tu écopes aussi de ses Pilis.",
        "flags": {"post_bet": "designate"},
    },
    {
        "key": "give",
        "title": "Cadeau empoisonné",
        "desc": "Après les paris, donne des cartes à ton voisin.",
        "flags": {"post_bet": "give"},
    },
]


def _feasible(template, n_players, hand):
    flags = template["flags"]
    if flags.get("bonus_card"):
        # il faut assez de cartes dans le paquet pour une carte de plus / joueur
        return hand * n_players + n_players <= (DECK_SIZE + 1)
    if flags.get("post_bet") == "give":
        return hand >= 2
    return True


def draw_mission(n_players, hand, avoid_key=None):
    """Pioche une Mission jouable et matérialise ses paramètres aléatoires."""
    pool = [t for t in MISSION_TEMPLATES
            if _feasible(t, n_players, hand) and t["key"] != avoid_key]
    if not pool:
        pool = [t for t in MISSION_TEMPLATES if _feasible(t, n_players, hand)]
    tpl = random.choice(pool)
    flags = dict(tpl["flags"])
    mission = {
        "key": tpl["key"],
        "title": tpl["title"],
        "desc": tpl["desc"],
        "expert": bool(tpl.get("expert")),
        "flags": flags,
    }
    if flags.get("cursed"):
        count = min(3, max(1, hand))
        mission["cursedNumbers"] = sorted(random.sample(range(1, DECK_SIZE + 1), count))
        nums = ", ".join(str(x) for x in mission["cursedNumbers"])
        mission["desc"] = f"Remporter un pli contenant un numéro maudit ({nums}) coûte 1 Pili."
    if flags.get("post_bet") == "give":
        flags["give_count"] = 1 if hand <= 3 else random.choice([1, 2])
        flags["give_dir"] = random.choice(["left", "right"])
        dir_fr = "gauche" if flags["give_dir"] == "left" else "droite"
        c = flags["give_count"]
        mission["desc"] = f"Après les paris, donne {c} carte{'s' if c > 1 else ''} à ton voisin de {dir_fr}."
    return mission


# ---------------------------------------------------------------------- #
# Joueur
# ---------------------------------------------------------------------- #
class Player:
    def __init__(self, player_id, name):
        self.id = player_id
        self.name = name
        self.sid = None
        self.connected = True
        self.pilis = 0
        self.hand = []
        self.bet = None
        self.tricks = 0


class GameError(Exception):
    pass


class Game:
    def __init__(self, room_id, cards_per_hand=DEFAULT_HAND, use_missions=True):
        self.room_id = room_id
        self.cards_per_hand = int(cards_per_hand)
        self.use_missions = bool(use_missions)
        self.players = []
        self.host_id = None
        self.phase = "lobby"   # lobby|rps|betting|post_bet|playing|round_end|game_over
        self.dealer_index = 0
        self.turn_index = 0
        self.current_trick = []
        self.round_number = 0
        self.last_trick = None
        self.round_summary = None
        self.winners = []
        self.log = []

        # Mission courante + état associé à la manche
        self.mission = None
        self.trick_number = 0
        self.tricks_total = 0
        self.round_extra = {}      # pilis de pénalité "mission" gagnés en cours de manche
        self.designations = {}     # id -> id désigné (mission designate)
        self.pending = set()       # joueurs devant encore agir en phase post_bet

        # Pierre-feuille-ciseaux
        self.rps_participants = []
        self.rps_choices = {}
        self.rps_last = None       # {throws:{id:shape}, tie:bool, eliminated:[ids]}

    # ------------------------- joueurs / connexions ------------------- #
    def get_player(self, player_id):
        return next((p for p in self.players if p.id == player_id), None)

    def player_by_sid(self, sid):
        return next((p for p in self.players if p.sid == sid), None)

    def add_or_reconnect(self, player_id, name, sid):
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

    # ------------------------------ démarrage ------------------------- #
    def start_game(self, player_id):
        if player_id != self.host_id:
            raise GameError("Seul l'hôte peut lancer la partie.")
        if self.phase != "lobby":
            raise GameError("La partie est déjà lancée.")
        if len(self.players) < MIN_PLAYERS:
            raise GameError("Il faut au moins 2 joueurs pour commencer.")
        need = self.cards_per_hand * len(self.players)
        if self.use_missions:
            need += len(self.players)  # marge pour la mission « carte surprise »
        if need > (DECK_SIZE + 1):
            raise GameError("Trop de cartes par joueur pour ce nombre de joueurs.")

        for p in self.players:
            p.pilis = 0
        self.round_number = 0
        self.winners = []
        # Le premier donneur est décidé au pierre-feuille-ciseaux.
        self.phase = "rps"
        self.rps_participants = [p.id for p in self.players]
        self.rps_choices = {}
        self.rps_last = None
        self._add_log("Pierre-feuille-ciseaux : qui commence ?")

    # --------------------- pierre-feuille-ciseaux --------------------- #
    def rps_choice(self, player_id, choice):
        if self.phase != "rps":
            raise GameError("Ce n'est pas le moment de jouer à pierre-feuille-ciseaux.")
        if player_id not in self.rps_participants:
            raise GameError("Tu n'es pas concerné par ce duel.")
        if choice not in RPS_BEATS:
            raise GameError("Choix invalide.")
        self.rps_choices[player_id] = choice
        # Tous les participants connectés ont-ils choisi ?
        ready = [pid for pid in self.rps_participants
                 if self.get_player(pid) and self.get_player(pid).connected]
        if all(pid in self.rps_choices for pid in ready) and ready:
            self._resolve_rps(ready)

    def _resolve_rps(self, ready):
        throws = {pid: self.rps_choices[pid] for pid in ready}
        shapes = set(throws.values())
        eliminated = []
        if len(shapes) == 2:
            a, b = list(shapes)
            winning = a if RPS_BEATS[a] == b else b
            survivors = [pid for pid in ready if throws[pid] == winning]
            eliminated = [pid for pid in ready if throws[pid] != winning]
            self.rps_participants = survivors
            tie = False
        else:
            # 1 seule forme (tous pareils) ou 3 formes -> égalité, on rejoue.
            tie = True

        self.rps_last = {
            "throws": throws,
            "tie": tie,
            "eliminated": eliminated,
        }
        self.rps_choices = {}

        if len(self.rps_participants) == 1:
            winner_id = self.rps_participants[0]
            winner = self.get_player(winner_id)
            self.dealer_index = self.players.index(winner)
            self._add_log(f"{winner.name} gagne le pierre-feuille-ciseaux et commence !")
            self._deal_round()
        elif tie:
            self._add_log("Égalité au pierre-feuille-ciseaux, on rejoue !")
        else:
            names = ", ".join(self.get_player(p).name for p in self.rps_participants)
            self._add_log(f"Départage entre {names}…")

    # ------------------------ distribution / manche ------------------- #
    def _deal_round(self):
        self.round_number += 1
        prev_key = self.mission["key"] if self.mission else None

        if self.use_missions:
            self.mission = draw_mission(len(self.players), self.cards_per_hand, avoid_key=prev_key)
        else:
            self.mission = None

        deck = make_deck()
        random.shuffle(deck)
        for p in self.players:
            p.hand = []
            p.bet = None
            p.tricks = 0

        n = len(self.players)
        idx = 0
        for _ in range(self.cards_per_hand):
            for offset in range(n):
                p = self.players[(self.dealer_index + offset) % n]
                p.hand.append(deck[idx])
                idx += 1
        self._deck_rest = deck[idx:]  # réserve pour la mission « carte surprise »

        for p in self.players:
            p.hand.sort(key=lambda c: (c["kind"] != "joker", c["value"] or 0))

        self.current_trick = []
        self.last_trick = None
        self.round_summary = None
        self.trick_number = 0
        self.tricks_total = self.cards_per_hand
        self.round_extra = {p.id: 0 for p in self.players}
        self.designations = {}
        self.pending = set()
        self.turn_index = self.dealer_index
        self.phase = "betting"
        m = f" · Mission : {self.mission['title']}" if self.mission else ""
        self._add_log(f"Manche {self.round_number}{m}. À vos paris !")

    def _flag(self, name, default=None):
        if not self.mission:
            return default
        return self.mission["flags"].get(name, default)

    # ------------------------------ paris ----------------------------- #
    def legal_bets(self, player):
        h = self.cards_per_hand
        options = list(range(0, h + 1))

        forbid = self._flag("forbid_bet")
        if forbid is not None:
            options = [b for b in options if b != forbid]

        if self._flag("no_copy"):
            placed = [p for p in self.players if p.bet is not None]
            if placed:
                prev_bet = placed[-1].bet
                options = [b for b in options if b != prev_bet]

        placed_count = sum(1 for p in self.players if p.bet is not None)
        is_last = placed_count == len(self.players) - 1
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
            raise GameError("Ce pari n'est pas autorisé ici.")

        player.bet = value
        self._add_log(f"{player.name} parie {value}.")

        if all(p.bet is not None for p in self.players):
            self._after_bets()
        else:
            self.turn_index = (self.turn_index + 1) % len(self.players)

    def _after_bets(self):
        """Applique les effets de mission déclenchés après les paris."""
        # Carte surprise : chacun pioche 1 carte en plus.
        if self._flag("bonus_card") and self._deck_rest:
            for p in self.players:
                if self._deck_rest:
                    p.hand.append(self._deck_rest.pop())
            for p in self.players:
                p.hand.sort(key=lambda c: (c["kind"] != "joker", c["value"] or 0))
            self.tricks_total = self.cards_per_hand + 1
            self._add_log("Chacun pioche une carte surprise.")

        # Missions demandant une action de chaque joueur avant de jouer.
        post = self._flag("post_bet")
        if post in ("designate", "give"):
            self.phase = "post_bet"
            self.pending = {p.id for p in self.players}
            self._add_log("Action de mission avant de jouer…")
            return

        self._start_playing()

    def _start_playing(self):
        self.phase = "playing"
        self.turn_index = self.dealer_index
        self.current_trick = []
        self._add_log("Les paris sont faits. À vous de jouer !")

    # --------------------- phase post-paris (missions) ---------------- #
    def _neighbor_id(self, player_id, direction):
        n = len(self.players)
        i = next(k for k, p in enumerate(self.players) if p.id == player_id)
        j = (i - 1) % n if direction == "left" else (i + 1) % n
        return self.players[j].id

    def set_designation(self, player_id, target_id):
        if self.phase != "post_bet" or self._flag("post_bet") != "designate":
            raise GameError("Aucune désignation attendue.")
        if player_id not in self.pending:
            raise GameError("Tu as déjà désigné un joueur.")
        target = self.get_player(target_id)
        if not target or target_id == player_id:
            raise GameError("Désigne un autre joueur.")
        self.designations[player_id] = target_id
        self.pending.discard(player_id)
        self._add_log(f"{self.get_player(player_id).name} a désigné quelqu'un.")
        if not self.pending:
            self._start_playing()

    def give_cards(self, player_id, card_ids):
        if self.phase != "post_bet" or self._flag("post_bet") != "give":
            raise GameError("Aucun cadeau attendu.")
        if player_id not in self.pending:
            raise GameError("Tu as déjà donné tes cartes.")
        count = self._flag("give_count", 1)
        if not isinstance(card_ids, list) or len(card_ids) != count:
            raise GameError(f"Choisis exactement {count} carte(s) à donner.")
        giver = self.get_player(player_id)
        chosen = [c for c in giver.hand if c["id"] in card_ids]
        if len(chosen) != count:
            raise GameError("Carte(s) invalide(s).")
        # On mémorise le don ; l'échange se fait quand tout le monde a choisi.
        self._pending_gifts = getattr(self, "_pending_gifts", {})
        self._pending_gifts[player_id] = list(chosen)
        self.pending.discard(player_id)
        self._add_log(f"{giver.name} a préparé son cadeau.")
        if not self.pending:
            self._apply_gifts()
            self._start_playing()

    def _apply_gifts(self):
        gifts = getattr(self, "_pending_gifts", {})
        direction = self._flag("give_dir", "left")
        # Retirer d'abord chez les donneurs, puis distribuer aux voisins.
        for pid, cards in gifts.items():
            giver = self.get_player(pid)
            for c in cards:
                if c in giver.hand:
                    giver.hand.remove(c)
        for pid, cards in gifts.items():
            target_id = self._neighbor_id(pid, direction)
            target = self.get_player(target_id)
            target.hand.extend(cards)
        for p in self.players:
            p.hand.sort(key=lambda c: (c["kind"] != "joker", c["value"] or 0))
        self._pending_gifts = {}

    # ------------------------------ valeurs --------------------------- #
    def _power(self, kind, value):
        """Force effective d'une carte (gère la mission « valeurs inversées »)."""
        if kind == "joker":
            return value  # le joueur choisit directement sa force (0..56)
        if self._flag("inverted"):
            return (DECK_SIZE + 1) - value  # 1 -> 55 (fort), 55 -> 1 (faible)
        return value

    def allowed_card_ids(self, player):
        """Cartes jouables pour le joueur courant (mission « tout ou rien »)."""
        if not self._flag("high_or_low"):
            return [c["id"] for c in player.hand]
        nums = [c for c in player.hand if c["kind"] == "num"]
        jokers = [c for c in player.hand if c["kind"] == "joker"]
        allowed = [j["id"] for j in jokers]  # le Joker est toujours jouable
        if nums:
            powers = [self._power("num", c["value"]) for c in nums]
            lo, hi = min(powers), max(powers)
            for c in nums:
                pw = self._power("num", c["value"])
                if pw == lo or pw == hi:
                    allowed.append(c["id"])
        return allowed

    # ------------------------------ jeu ------------------------------- #
    def play_card(self, player_id, card_id, joker_value=None):
        if self.phase != "playing":
            raise GameError("Ce n'est pas le moment de jouer une carte.")
        player = self.players[self.turn_index]
        if player.id != player_id:
            raise GameError("Ce n'est pas votre tour.")
        card = next((c for c in player.hand if c["id"] == card_id), None)
        if card is None:
            raise GameError("Vous n'avez pas cette carte.")
        if card_id not in self.allowed_card_ids(player):
            raise GameError("Mission « tout ou rien » : joue ta carte la plus forte ou la plus faible.")

        if card["kind"] == "joker":
            if joker_value is None:
                raise GameError("Choisissez une valeur pour le Joker.")
            try:
                joker_value = int(joker_value)
            except (TypeError, ValueError):
                raise GameError("Valeur de Joker invalide.")
            if not (JOKER_MIN <= joker_value <= JOKER_MAX):
                raise GameError(f"Le Joker doit valoir entre {JOKER_MIN} et {JOKER_MAX}.")
            face, power = joker_value, self._power("joker", joker_value)
        else:
            face, power = card["value"], self._power("num", card["value"])

        player.hand.remove(card)
        self.current_trick.append({
            "player_id": player.id,
            "player_name": player.name,
            "value": face,          # valeur affichée (face de la carte)
            "power": power,          # force effective (pour départager)
            "is_joker": card["kind"] == "joker",
        })

        if len(self.current_trick) == len(self.players):
            self._resolve_trick()
        else:
            self.turn_index = (self.turn_index + 1) % len(self.players)

    def _resolve_trick(self):
        self.trick_number += 1
        best_i = 0
        for i in range(1, len(self.current_trick)):
            if self.current_trick[i]["power"] > self.current_trick[best_i]["power"]:
                best_i = i
        winner_id = self.current_trick[best_i]["player_id"]
        winner = self.get_player(winner_id)
        winner.tricks += 1

        # --- Pénalités de mission liées aux plis ---
        if self._flag("cursed"):
            cursed = set(self.mission.get("cursedNumbers", []))
            if any((not c["is_joker"]) and c["value"] in cursed for c in self.current_trick):
                self.round_extra[winner_id] += 1
                self._add_log(f"{winner.name} ramasse un pli maudit (+1 Pili).")

        if self._flag("first_last_penalty"):
            is_first = self.trick_number == 1
            is_last = self.trick_number == self.tricks_total
            if is_first or is_last:
                self.round_extra[winner_id] += 1
                self._add_log(f"{winner.name} remporte un pli piégé (+1 Pili).")

        self.last_trick = {
            "cards": list(self.current_trick),
            "winner_id": winner_id,
            "winner_name": winner.name,
        }
        self._add_log(f"{winner.name} remporte le pli.")

        self.turn_index = self.players.index(winner)
        self.current_trick = []

        if all(len(p.hand) == 0 for p in self.players):
            self._resolve_round()

    def _resolve_round(self):
        gaps = {p.id: abs(p.bet - p.tricks) for p in self.players}
        gained = {p.id: gaps[p.id] + self.round_extra.get(p.id, 0) for p in self.players}

        # Mission « pari libérateur » : pari réussi -> on défausse des Pilis.
        if self._flag("discard_on_success"):
            for p in self.players:
                if gaps[p.id] == 0 and p.bet > 0:
                    gained[p.id] = -min(p.bet, p.pilis)

        # Mission « fardeau partagé » : on ajoute les Pilis du joueur désigné.
        if self._flag("post_bet") == "designate":
            base = dict(gained)
            for p in self.players:
                t = self.designations.get(p.id)
                if t is not None:
                    gained[p.id] = base[p.id] + max(0, base.get(t, 0))

        summary = []
        for p in self.players:
            g = gained[p.id]
            p.pilis = max(0, p.pilis + g)
            summary.append({
                "player_id": p.id,
                "name": p.name,
                "bet": p.bet,
                "tricks": p.tricks,
                "gained": g,
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
        self.mission = None
        self.rps_last = None
        for p in self.players:
            p.pilis = 0
            p.hand = []
            p.bet = None
            p.tricks = 0
        self.current_trick = []
        self.last_trick = None
        self.round_summary = None
        self._add_log("Nouvelle partie ! En attente du lancement.")

    # ---------------------- sérialisation par joueur ------------------ #
    def _public_mission(self):
        if not self.mission:
            return None
        f = self.mission["flags"]
        return {
            "key": self.mission["key"],
            "title": self.mission["title"],
            "desc": self.mission["desc"],
            "expert": self.mission["expert"],
            "inverted": bool(f.get("inverted")),
            "openHands": bool(f.get("open_hands")),
            "cursedNumbers": self.mission.get("cursedNumbers"),
        }

    def state_for(self, player_id):
        me = self.get_player(player_id)
        turn_player = self.players[self.turn_index] if self.players else None
        turn_id = turn_player.id if (turn_player and self.phase in ("betting", "playing")) else None

        hide_my_hand = self._flag("bet_blind") and self.phase == "betting"
        open_hands = self._flag("open_hands") and self.phase in ("post_bet", "playing")

        players_view = []
        for i, p in enumerate(self.players):
            entry = {
                "id": p.id,
                "name": p.name,
                "connected": p.connected,
                "pilis": p.pilis,
                "bet": p.bet,
                "tricks": p.tricks,
                "handCount": len(p.hand),
                "isDealer": i == self.dealer_index and self.phase not in ("lobby", "rps"),
                "isTurn": turn_id is not None and p.id == turn_id,
                "isHost": p.id == self.host_id,
                "isYou": p.id == player_id,
            }
            if open_hands and p.id != player_id:
                entry["hand"] = list(p.hand)
            players_view.append(entry)

        state = {
            "roomId": self.room_id,
            "phase": self.phase,
            "cardsPerHand": self.cards_per_hand,
            "useMissions": self.use_missions,
            "maxPilis": MAX_PILIS,
            "roundNumber": self.round_number,
            "hostId": self.host_id,
            "players": players_view,
            "currentTrick": list(self.current_trick),
            "lastTrick": self.last_trick,
            "turnPlayerId": turn_id,
            "log": list(self.log),
            "mission": self._public_mission(),
            "you": {
                "id": me.id if me else None,
                "name": me.name if me else None,
                "hand": [] if hide_my_hand else (list(me.hand) if me else []),
                "handHidden": bool(hide_my_hand),
                "handCount": len(me.hand) if me else 0,
                "bet": me.bet if me else None,
                "isHost": bool(me and me.id == self.host_id),
            },
            "yourTurn": turn_id is not None and me is not None and me.id == turn_id,
            "jokerRange": [JOKER_MIN, JOKER_MAX],
        }

        if self.phase == "betting" and state["yourTurn"] and me is not None:
            state["legalBets"] = self.legal_bets(me)

        if self.phase == "playing" and state["yourTurn"] and me is not None and self._flag("high_or_low"):
            state["allowedCardIds"] = self.allowed_card_ids(me)

        if self.phase == "rps":
            state["rps"] = self._rps_view(player_id)

        if self.phase == "post_bet":
            state["postBet"] = self._post_bet_view(player_id)

        if self.phase in ("round_end", "game_over"):
            state["roundSummary"] = self.round_summary
        if self.phase == "game_over":
            state["winners"] = [{"id": w, "name": self.get_player(w).name} for w in self.winners]
        if self.phase == "lobby":
            state["canStart"] = bool(me and me.id == self.host_id) and len(self.players) >= MIN_PLAYERS

        return state

    def _rps_view(self, player_id):
        me_in = player_id in self.rps_participants
        waiting = [self.get_player(pid).name for pid in self.rps_participants
                   if pid not in self.rps_choices and self.get_player(pid)]
        last = None
        if self.rps_last:
            last = {
                "throws": [
                    {"name": self.get_player(pid).name if self.get_player(pid) else "?",
                     "choice": ch,
                     "eliminated": pid in self.rps_last["eliminated"]}
                    for pid, ch in self.rps_last["throws"].items()
                ],
                "tie": self.rps_last["tie"],
            }
        return {
            "amParticipant": me_in,
            "hasChosen": player_id in self.rps_choices,
            "participants": [self.get_player(pid).name for pid in self.rps_participants
                             if self.get_player(pid)],
            "waitingOn": waiting,
            "lastResult": last,
        }

    def _post_bet_view(self, player_id):
        post = self._flag("post_bet")
        submitted = player_id not in self.pending
        view = {"type": post, "submitted": submitted}
        if post == "designate":
            view["options"] = [{"id": p.id, "name": p.name}
                               for p in self.players if p.id != player_id]
        elif post == "give":
            view["count"] = self._flag("give_count", 1)
            direction = self._flag("give_dir", "left")
            view["direction"] = "gauche" if direction == "left" else "droite"
            view["toName"] = self.get_player(self._neighbor_id(player_id, direction)).name
        return view
