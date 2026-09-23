/* ============================================================
   Pili Pili — client temps réel
   ============================================================ */
"use strict";

// ---- Identité persistante du joueur (survit aux rafraîchissements) ----
function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}
let playerId = localStorage.getItem("pp_playerId");
if (!playerId) { playerId = uuid(); localStorage.setItem("pp_playerId", playerId); }

let roomId = null;
let state = null;

const socket = io({ transports: ["websocket", "polling"] });

// ---- Raccourcis DOM ----
const $ = (id) => document.getElementById(id);
const lobby = $("lobby");
const gameView = $("game");

// ---------------------------------------------------------------------- //
// Connexion / reconnexion
// ---------------------------------------------------------------------- //
socket.on("connect", () => {
  setConn("Connecté", true);
  // Reconnexion automatique si on était déjà dans un salon (refresh, coupure).
  const savedRoom = sessionStorage.getItem("pp_room");
  if (savedRoom) {
    socket.emit("join_room", {
      roomId: savedRoom,
      playerId,
      name: localStorage.getItem("pp_name") || "",
    });
  }
});
socket.on("disconnect", () => setConn("Reconnexion…", false));
socket.on("connect_error", () => setConn("Serveur injoignable…", false));

socket.on("joined", (data) => {
  roomId = data.roomId;
  sessionStorage.setItem("pp_room", roomId);
  updateUrl(roomId);
  showGame();
});

socket.on("error_msg", (data) => toast(data.message || "Action impossible."));

socket.on("game_state", (s) => {
  state = s;
  render();
});

function setConn(text, ok) {
  const el = $("conn-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("ok", !!ok);
}

// ---------------------------------------------------------------------- //
// Lobby : création / rejoindre
// ---------------------------------------------------------------------- //
(function initLobby() {
  const params = new URLSearchParams(location.search);
  const invited = (params.get("room") || "").toUpperCase();
  const savedName = localStorage.getItem("pp_name") || "";
  $("name-input").value = savedName;

  if (invited) {
    $("join-code").textContent = invited;
    $("join-block").classList.remove("hidden");
    $("create-block").classList.add("hidden");
  }

  $("create-btn").addEventListener("click", () => {
    const name = requireName();
    if (!name) return;
    socket.emit("create_room", {
      name,
      playerId,
      cardsPerHand: parseInt($("cards-select").value, 10),
    });
  });

  $("join-btn").addEventListener("click", () => {
    const name = requireName();
    if (!name) return;
    socket.emit("join_room", { roomId: invited, playerId, name });
  });

  $("join-manual-btn").addEventListener("click", () => {
    const name = requireName();
    if (!name) return;
    const code = ($("code-input").value || "").trim().toUpperCase();
    if (!code) { toast("Entre un code de salon."); return; }
    socket.emit("join_room", { roomId: code, playerId, name });
  });
})();

function requireName() {
  const name = ($("name-input").value || "").trim();
  if (!name) { toast("Choisis d'abord un pseudo."); return null; }
  localStorage.setItem("pp_name", name);
  return name;
}

function updateUrl(code) {
  const url = new URL(location.href);
  url.searchParams.set("room", code);
  history.replaceState(null, "", url.toString());
}

function showGame() {
  lobby.classList.add("hidden");
  gameView.classList.remove("hidden");
}

// ---------------------------------------------------------------------- //
// Rendu principal
// ---------------------------------------------------------------------- //
function render() {
  if (!state) return;
  $("room-code").textContent = state.roomId;

  // Bandeau info manche
  const ri = $("round-info");
  if (state.phase === "lobby") {
    ri.innerHTML = `<b>${state.players.length}</b> joueur(s) · ${state.cardsPerHand} cartes/joueur`;
  } else {
    ri.innerHTML = `Manche <b>${state.roundNumber}</b> · fin à <b>${state.maxPilis}</b> 🌶️`;
  }

  renderOpponents();
  renderTable();
  renderMeArea();
  renderSummaryModal();
}

// ---- Adversaires (et soi, en résumé) ----
function renderOpponents() {
  const box = $("opponents");
  box.innerHTML = "";
  state.players.forEach((p) => {
    const chip = document.createElement("div");
    chip.className = "player-chip";
    if (p.isTurn) chip.classList.add("turn");
    if (!p.connected) chip.classList.add("disconnected");

    const badges = [];
    if (p.isDealer) badges.push('<span class="badge dealer">Donneur</span>');
    if (p.isHost) badges.push('<span class="badge">Hôte</span>');
    if (!p.connected) badges.push('<span class="badge">Hors ligne</span>');

    const betTxt = p.bet === null || p.bet === undefined ? "—" : p.bet;
    const showBets = state.phase === "betting" || state.phase === "playing";

    chip.innerHTML = `
      <div class="pc-top">
        <span class="pc-name">${escapeHtml(p.name)}${p.isYou ? " (toi)" : ""}</span>
        ${badges.join("")}
      </div>
      ${showBets ? `<div class="pc-stats"><span>Pari : <b>${betTxt}</b></span><span>Plis : <b>${p.tricks}</b></span></div>` : ""}
      <div class="pilis-row">${chilis(p.pilis)} <span style="color:var(--muted)">${p.pilis}/${state.maxPilis}</span></div>
    `;
    box.appendChild(chip);
  });
}

// ---- Table centrale ----
function renderTable() {
  const banner = $("phase-banner");
  const trick = $("trick-area");
  const log = $("table-log");
  trick.innerHTML = "";
  log.textContent = state.log && state.log.length ? state.log[state.log.length - 1] : "";

  if (state.phase === "lobby") {
    banner.innerHTML = "En attente du lancement de la partie…";
    return;
  }

  // Bandeau selon la phase / le tour
  const turnName = playerName(state.turnPlayerId);
  if (state.phase === "betting") {
    banner.innerHTML = state.yourTurn
      ? `<span class="hl">À toi de parier !</span>`
      : `En attente du pari de <span class="hl">${escapeHtml(turnName)}</span>…`;
  } else if (state.phase === "playing") {
    banner.innerHTML = state.yourTurn
      ? `<span class="hl">À toi de jouer une carte !</span>`
      : `Au tour de <span class="hl">${escapeHtml(turnName)}</span>…`;
  } else if (state.phase === "round_end") {
    banner.innerHTML = "Manche terminée.";
  } else if (state.phase === "game_over") {
    banner.innerHTML = "Partie terminée !";
  }

  // Cartes en jeu : pli en cours, sinon dernier pli résolu.
  let cards = state.currentTrick;
  let winnerId = null;
  if ((!cards || cards.length === 0) && state.lastTrick) {
    cards = state.lastTrick.cards;
    winnerId = state.lastTrick.winner_id;
  }
  (cards || []).forEach((c) => {
    const slot = document.createElement("div");
    slot.className = "trick-slot";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = c.player_name;
    const el = trickCard(c, c.player_id === winnerId);
    slot.appendChild(who);
    slot.appendChild(el);
    trick.appendChild(slot);
  });
}

// ---- Zone du joueur (paris / main / actions hôte) ----
function renderMeArea() {
  const betControls = $("bet-controls");
  const handBlock = $("hand-block");
  const handEl = $("hand");
  const handTitle = $("hand-title");
  const hostActions = $("host-actions");
  hostActions.innerHTML = "";
  betControls.classList.add("hidden");

  // --- Lobby ---
  if (state.phase === "lobby") {
    handBlock.classList.add("hidden");
    if (state.you.isHost) {
      if (state.canStart) {
        const b = button("Lancer la partie", "btn btn-primary", () => socket.emit("start_game", {}));
        hostActions.appendChild(b);
      } else {
        note(hostActions, "Il faut au moins 2 joueurs. Partage le lien pour inviter.");
      }
    } else {
      note(hostActions, "En attente que l'hôte lance la partie…");
    }
    return;
  }

  // --- Betting / Playing : afficher la main ---
  handBlock.classList.remove("hidden");
  const myBet = state.you.bet;
  handTitle.textContent =
    myBet === null || myBet === undefined
      ? "Ta main"
      : `Ta main · Pari : ${myBet}`;

  // Paris
  if (state.phase === "betting" && state.yourTurn && state.legalBets) {
    betControls.classList.remove("hidden");
    const bb = $("bet-buttons");
    bb.innerHTML = "";
    state.legalBets.forEach((v) => {
      bb.appendChild(button(String(v), "btn bet-btn", () => socket.emit("place_bet", { bet: v })));
    });
  }

  // Main
  const playable = state.phase === "playing" && state.yourTurn;
  handEl.className = "hand" + (playable ? "" : " disabled");
  handEl.innerHTML = "";
  (state.you.hand || []).forEach((card) => {
    handEl.appendChild(handCard(card, playable));
  });

  if ((state.you.hand || []).length === 0 && state.phase === "playing") {
    note(hostActions, "Tu as joué toutes tes cartes.");
  }
}

// ---------------------------------------------------------------------- //
// Modale de bilan (fin de manche / fin de partie)
// ---------------------------------------------------------------------- //
function renderSummaryModal() {
  const modal = $("summary-modal");
  const title = $("summary-title");
  const body = $("summary-body");
  const actions = $("summary-actions");

  if (state.phase !== "round_end" && state.phase !== "game_over") {
    modal.classList.add("hidden");
    return;
  }

  const rows = (state.roundSummary || [])
    .slice()
    .sort((a, b) => a.total - b.total);
  const winnerIds = (state.winners || []).map((w) => w.id);

  let html = `<table class="summary-table"><thead><tr>
      <th>Joueur</th><th>Pari</th><th>Plis</th><th>+ Pilis</th><th>Total</th></tr></thead><tbody>`;
  rows.forEach((r) => {
    const win = winnerIds.includes(r.player_id);
    html += `<tr class="${win ? "win-row" : ""}">
      <td>${escapeHtml(r.name)}${win ? " 🏆" : ""}</td>
      <td>${r.bet}</td><td>${r.tricks}</td>
      <td class="${r.gained === 0 ? "ok" : "bad"}">${r.gained === 0 ? "0" : "+" + r.gained}</td>
      <td>${r.total} 🌶️</td></tr>`;
  });
  html += "</tbody></table>";

  actions.innerHTML = "";

  if (state.phase === "game_over") {
    const names = (state.winners || []).map((w) => escapeHtml(w.name)).join(", ");
    title.textContent = "Partie terminée !";
    body.innerHTML = `<div class="trophy">🏆</div>
      <p style="color:var(--gold);font-weight:700">Vainqueur : ${names}</p>${html}`;
    if (state.you.isHost) {
      actions.appendChild(button("Rejouer", "btn btn-primary", () => socket.emit("restart_game", {})));
    } else {
      note(actions, "En attente d'une nouvelle partie…");
    }
  } else {
    title.textContent = `Fin de la manche ${state.roundNumber}`;
    body.innerHTML = html;
    if (state.you.isHost) {
      actions.appendChild(button("Manche suivante", "btn btn-primary", () => socket.emit("next_round", {})));
    } else {
      note(actions, "En attente de l'hôte pour la manche suivante…");
    }
  }

  modal.classList.remove("hidden");
}

// ---------------------------------------------------------------------- //
// Cartes (DOM)
// ---------------------------------------------------------------------- //
function handCard(card, playable) {
  const el = baseCard(card);
  if (playable) {
    el.classList.add("playable");
    el.addEventListener("click", () => {
      if (card.kind === "joker") openJokerModal(card.id);
      else socket.emit("play_card", { cardId: card.id });
    });
  }
  return el;
}

function trickCard(entry, isWinner) {
  const fake = entry.is_joker
    ? { kind: "joker", value: entry.value, joutedValue: entry.value }
    : { kind: "num", value: entry.value };
  const el = baseCard(fake, entry.is_joker ? entry.value : null);
  el.classList.add("trick-card");
  if (isWinner) el.classList.add("winner");
  return el;
}

function baseCard(card, jokerShownValue) {
  const el = document.createElement("div");
  el.className = "card";
  if (card.kind === "joker") {
    el.classList.add("joker");
    const shown = jokerShownValue !== undefined && jokerShownValue !== null ? jokerShownValue : "🔥";
    el.innerHTML = `<div class="num">${shown}</div><div class="label">JOKER</div>`;
  } else {
    el.innerHTML = `
      <div class="corner tl">${card.value}</div>
      <div class="pip a">🌶️</div>
      <div class="num">${card.value}</div>
      <div class="pip b">🌶️</div>
      <div class="corner br">${card.value}</div>`;
  }
  return el;
}

// ---------------------------------------------------------------------- //
// Modale Joker
// ---------------------------------------------------------------------- //
let jokerCardId = null;
(function initJoker() {
  const modal = $("joker-modal");
  const slider = $("joker-slider");
  const valEl = $("joker-value");
  slider.addEventListener("input", () => (valEl.textContent = slider.value));
  document.querySelectorAll(".joker-quick .btn").forEach((b) => {
    b.addEventListener("click", () => {
      slider.value = b.dataset.v;
      valEl.textContent = b.dataset.v;
    });
  });
  $("joker-cancel").addEventListener("click", () => modal.classList.add("hidden"));
  $("joker-confirm").addEventListener("click", () => {
    modal.classList.add("hidden");
    socket.emit("play_card", { cardId: jokerCardId, jokerValue: parseInt(slider.value, 10) });
  });
})();
function openJokerModal(cardId) {
  jokerCardId = cardId;
  const [lo, hi] = state.jokerRange || [0, 56];
  const slider = $("joker-slider");
  slider.min = lo; slider.max = hi;
  $("joker-modal").classList.remove("hidden");
}

// ---------------------------------------------------------------------- //
// Barre du haut : copier le lien
// ---------------------------------------------------------------------- //
$("copy-btn").addEventListener("click", async () => {
  const link = `${location.origin}/?room=${roomId}`;
  try {
    await navigator.clipboard.writeText(link);
    toast("Lien copié ! Envoie-le à ta copine 🌶️");
  } catch (e) {
    prompt("Copie ce lien :", link);
  }
});

// ---------------------------------------------------------------------- //
// Petits utilitaires
// ---------------------------------------------------------------------- //
function button(label, cls, onClick) {
  const b = document.createElement("button");
  b.className = cls;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}
function note(parent, text) {
  const p = document.createElement("p");
  p.className = "waiting-note";
  p.textContent = text;
  parent.appendChild(p);
}
function playerName(id) {
  if (!id || !state) return "";
  const p = state.players.find((x) => x.id === id);
  return p ? p.name : "";
}
function chilis(n) {
  if (!n) return '<span style="color:var(--muted)">—</span>';
  return "🌶️".repeat(Math.min(n, 7));
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}
