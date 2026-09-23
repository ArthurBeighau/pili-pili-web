"""
Serveur temps réel pour Pili Pili.

Stack : Flask + Flask-SocketIO en mode "threading" (avec simple-websocket),
le choix le plus compatible avec les versions récentes de Python et le plus
simple à déployer sur un hébergeur gratuit comme Render.

Toutes les parties sont stockées en mémoire du processus. Sur Render (free),
il faut lancer un SEUL worker (-w 1), ce qui garantit un état partagé cohérent
et le bon fonctionnement de Socket.IO.
"""

import os

from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit

from game import Game, GameError, new_room_code, MIN_HAND, MAX_HAND

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "pili-pili-dev-secret")

# async_mode="threading" -> pas de monkey-patching, compatible Python 3.10+.
# cors_allowed_origins="*" simplifie l'usage depuis n'importe quel appareil.
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# room_code -> Game
rooms = {}


# ---------------------------------------------------------------------- #
# Page unique
# ---------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return {"status": "ok", "rooms": len(rooms)}


# ---------------------------------------------------------------------- #
# Utilitaires de diffusion
# ---------------------------------------------------------------------- #
def broadcast_state(game):
    """Envoie à CHAQUE joueur connecté un état personnalisé (sa main reste
    privée). On émet vers le sid individuel de chaque joueur."""
    for p in game.players:
        if p.connected and p.sid:
            socketio.emit("game_state", game.state_for(p.id), to=p.sid)


def send_error(message):
    emit("error_msg", {"message": message}, to=request.sid)


def find_room_by_sid(sid):
    for game in rooms.values():
        if game.player_by_sid(sid):
            return game
    return None


# ---------------------------------------------------------------------- #
# Événements Socket.IO
# ---------------------------------------------------------------------- #
@socketio.on("create_room")
def on_create_room(data):
    data = data or {}
    name = (data.get("name") or "").strip()
    player_id = (data.get("playerId") or "").strip()
    if not player_id:
        return send_error("Identifiant joueur manquant.")

    try:
        cards = int(data.get("cardsPerHand", 5))
    except (TypeError, ValueError):
        cards = 5
    cards = max(MIN_HAND, min(MAX_HAND, cards))

    code = new_room_code(rooms.keys())
    game = Game(code, cards_per_hand=cards)
    rooms[code] = game
    try:
        game.add_or_reconnect(player_id, name, request.sid)
    except GameError as e:
        return send_error(str(e))

    join_room(code)
    emit("joined", {"roomId": code, "playerId": player_id})
    broadcast_state(game)


@socketio.on("join_room")
def on_join_room(data):
    data = data or {}
    code = (data.get("roomId") or "").strip().upper()
    name = (data.get("name") or "").strip()
    player_id = (data.get("playerId") or "").strip()
    if not player_id:
        return send_error("Identifiant joueur manquant.")

    game = rooms.get(code)
    if not game:
        return send_error("Salon introuvable. Vérifiez le code.")

    try:
        game.add_or_reconnect(player_id, name, request.sid)
    except GameError as e:
        return send_error(str(e))

    join_room(code)
    emit("joined", {"roomId": code, "playerId": player_id})
    broadcast_state(game)


@socketio.on("start_game")
def on_start_game(data):
    game = find_room_by_sid(request.sid)
    if not game:
        return send_error("Vous n'êtes dans aucun salon.")
    p = game.player_by_sid(request.sid)
    try:
        game.start_game(p.id)
    except GameError as e:
        return send_error(str(e))
    broadcast_state(game)


@socketio.on("place_bet")
def on_place_bet(data):
    data = data or {}
    game = find_room_by_sid(request.sid)
    if not game:
        return send_error("Vous n'êtes dans aucun salon.")
    p = game.player_by_sid(request.sid)
    try:
        game.place_bet(p.id, data.get("bet"))
    except GameError as e:
        return send_error(str(e))
    broadcast_state(game)


@socketio.on("play_card")
def on_play_card(data):
    data = data or {}
    game = find_room_by_sid(request.sid)
    if not game:
        return send_error("Vous n'êtes dans aucun salon.")
    p = game.player_by_sid(request.sid)
    try:
        game.play_card(p.id, data.get("cardId"), data.get("jokerValue"))
    except GameError as e:
        return send_error(str(e))
    broadcast_state(game)


@socketio.on("next_round")
def on_next_round(data):
    game = find_room_by_sid(request.sid)
    if not game:
        return send_error("Vous n'êtes dans aucun salon.")
    p = game.player_by_sid(request.sid)
    try:
        game.next_round(p.id)
    except GameError as e:
        return send_error(str(e))
    broadcast_state(game)


@socketio.on("restart_game")
def on_restart_game(data):
    game = find_room_by_sid(request.sid)
    if not game:
        return send_error("Vous n'êtes dans aucun salon.")
    p = game.player_by_sid(request.sid)
    try:
        game.restart(p.id)
    except GameError as e:
        return send_error(str(e))
    broadcast_state(game)


@socketio.on("disconnect")
def on_disconnect():
    game = find_room_by_sid(request.sid)
    if game:
        game.mark_disconnected(request.sid)
        broadcast_state(game)
        # Nettoyage : si le salon est vide et jamais démarré, on l'oublie.
        if all(not p.connected for p in game.players) and game.phase == "lobby":
            rooms.pop(game.room_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # allow_unsafe_werkzeug=True : nécessaire pour lancer le serveur de dev
    # en mode threading hors debug (usage local uniquement).
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
