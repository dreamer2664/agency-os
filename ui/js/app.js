// app.js — boot the deck: rail, watch, taskbar, palette, live wiring.
import { api, subscribe } from "./api.js";
import { h, icon, brandMark, $, clamp, debounce, toast, fmtClock, fmtAge, parseTs } from "./util.js";
import { WindowManager } from "./wm.js";
import { bus, emptyState } from "./views/common.js";
import { overview } from "./views/overview.js";
import { agents } from "./views/agents.js";
import { board } from "./views/board.js";
import { comms } from "./views/comms.js";
import { review } from "./views/review.js";
import { repos } from "./views/repos.js";
import { records } from "./views/records.js";
import { resources, settings } from "./views/ops.js";

const VIEWS = { overview, agents, board, comms, review, repos, records, resources, settings };
const RAIL = [
  { group: "Agency", items: ["overview", "agents", "board", "comms"] },
  { group: "Control", items: ["review", "repos", "records"] },
  { group: "System", items: ["resources", "settings"] },
];

const app = {
  wm: null,
  summary: null,
  config: null,
  conn: "connecting",
  lastActivity: null,
};

/* --------------------------------------------------------------------- boot */
async function boot() {
  const bootEl = $("#boot");
  const step = $("#boot-step");
  const steps = ["reading roster", "reading board", "opening the record", "establishing the watch"];
  let i = 0;
  const cycle = setInterval(() => { step.textContent = steps[i++ % steps.length] + "…"; }, 420);

  document.documentElement.dataset.theme = localStorage.getItem("agencyos.theme") || "graphite";
  app.wm = new WindowManager($("#desk"), { onChange: () => renderTaskbar() });
  buildRail();
  buildTopbar();
  buildWatch();
  buildTaskbar();
  bindKeys();
  buildPalette();

  try {
    app.config = await api.config();
    document.title = "AGENCY OS · command deck";
    app.summary = await api.summary();
    renderChrome(app.summary);
    openView((location.hash || "#overview").slice(1));
    if (!new URLSearchParams(location.search).has("still")) startLive();
    const total = performance.now();
    step.textContent = `ready in ${Math.round(total)} ms`;
  } catch (err) {
    step.textContent = "agencyd unreachable";
    showFatal(err);
    clearInterval(cycle);
    return;
  }
  clearInterval(cycle);
  // captured? still=1 disables live updates (screenshots, demos); boot=0 hides the splash at once
  const finishBoot = () => {
    bootEl.dataset.done = "true";
    // drop the splash from the DOM: a hidden element with running animations
    // still costs compositor memory for the life of the session
    setTimeout(() => bootEl.remove(), 700);
  };
  if (new URLSearchParams(location.search).get("boot") === "0") finishBoot();
  else setTimeout(finishBoot, 260);
  setInterval(tickClock, 1000);
  tickClock();
  setInterval(pollSummary, 20000);
  setInterval(pollResources, 15000);
  pollResources();
}

function showFatal(err) {
  $("#stage").replaceChildren(
    h("div", { class: "fatal" },
      h("div", { class: "label" }, "The deck cannot see the agency"),
      h("h1", { text: err.message }),
      h("p", { class: "dim" }, "Start the daemon with ", h("code", {}, "agencyos up"),
        " — the interface stays empty rather than inventing a crew.")),
  );
}

/* ---------------------------------------------------------------- structure */
function buildRail() {
  const rail = $("#rail");
  const nav = h("nav", { class: "rail-section", "aria-label": "Panels" });
  for (const { group, items } of RAIL) {
    nav.append(h("div", { class: "rail-title", text: group }));
    for (const id of items) {
      const v = VIEWS[id];
      nav.append(h("button", {
        class: "nav-item", dataset: { view: id }, "aria-current": "false",
        onclick: () => openView(id),
        title: v.title,
      }, icon(v.icon, 15), h("span", { text: v.title.replace("Agency ", "") }),
        h("span", { class: "nav-badge", dataset: { badge: id } })));
    }
  }
  rail.replaceChildren(nav,
    h("div", { class: "rail-foot" },
      h("div", { class: "rail-meta" },
        h("div", {}, h("b", {}, "AGENCY OS")),
        h("div", { id: "rail-version" }, `v${"—"}`),
        h("div", { id: "rail-source" }, "sources —"))));
}

function buildTopbar() {
  const bar = $("#topbar");
  const brand = h("div", { class: "brand" },
    h("span", { class: "brand-mark" }, brandMark(26)),
    h("div", { class: "brand-text" },
      h("div", { class: "brand-name", text: "AGENCY OS" }),
      h("div", { class: "brand-sub", text: "command deck" })));
  const status = h("div", { class: "org-status" },
    h("span", { class: "status-word", id: "status-word", text: "SYNCING" }),
    h("span", { class: "status-detail", id: "status-detail", text: "…" }));
  const kpis = h("div", { class: "kpis", id: "kpis" });
  const actions = h("div", { class: "top-actions" },
    h("button", { class: "btn ghost", onclick: openPalette, title: "Command palette (Ctrl K)" },
      icon("search", 13), "Search", h("kbd", { style: { marginLeft: "2px" } }, "⌘K")),
    h("span", { class: "conn", id: "conn", dataset: { state: "connecting" }, text: "linking" }),
    h("div", { class: "clock" },
      h("div", { class: "clock-utc", id: "clock-utc", text: "--:--:--" }),
      h("div", { class: "clock-local", id: "clock-local", text: "local" })));
  bar.replaceChildren(brand, status, kpis, actions);
}

function buildWatch() {
  const el = $("#watch");
  el.replaceChildren(
    h("div", { class: "watch-head" },
      h("span", { class: "watch-eye" }, icon("eye", 14)),
      h("span", { class: "watch-title", text: "SURVEILLANCE" }),
      h("span", { class: "watch-live" }, h("i"), "WATCHING")),
    h("div", { class: "watch-body", id: "watch-body" }),
    h("div", { class: "watch-foot", id: "watch-foot" }),
  );
}

function buildTaskbar() {
  const tb = $("#taskbar");
  tb.replaceChildren(
    h("button", { class: "tb-start", onclick: openPalette }, brandMark(13), "AGENCY"),
    h("span", { class: "tb-sep" }),
    h("div", { class: "tb-windows", id: "tb-windows" }),
    h("div", { class: "tb-status" },
      h("span", { id: "tb-mem", title: "agencyd process tree RSS" }, "— MB"),
      h("span", { class: "tb-sep" }),
      h("span", { id: "tb-silence", title: "time since anything moved" }, "—"),
      h("span", { class: "tb-sep" }),
      h("span", { class: "mono", id: "tb-clock", text: "--:--" })),
  );
}

/* ----------------------------------------------------------------- chrome */
function renderChrome(s) {
  const st = s.status;
  const word = $("#status-word");
  word.textContent = st.label;
  word.dataset.code = st.code;
  $("#status-detail").textContent = st.detail;

  const kpis = [
    { v: s.agents.alive, k: "alive", cls: s.agents.alive ? "" : "bad", go: "agents" },
    { v: s.board.open, k: "unclaimed", cls: s.board.open ? "warn" : "", go: "board" },
    { v: s.board.review, k: "review", cls: "", go: "review" },
    { v: s.board.blocked, k: "blocked", cls: s.board.blocked ? "bad" : "", go: "board" },
    { v: s.wire.last_24h, k: "wire 24h", cls: "", go: "records" },
  ];
  $("#kpis").replaceChildren(...kpis.map((x) => h("div", {
    class: "kpi", onclick: () => openView(x.go), style: { cursor: "pointer" }, title: `${x.k}: ${x.v}`,
  }, h("div", { class: `kpi-value ${x.cls}`, text: String(x.v) }),
    h("div", { class: "kpi-label", text: x.k }))));

  const navBadges = {
    board: [s.board.live, s.board.blocked ? "hot" : ""],
    review: [s.board.review, s.board.review ? "hot" : ""],
    agents: [s.agents.alive, ""],
    comms: [s.wire.last_24h, ""],
  };
  for (const [id, [count, cls]] of Object.entries(navBadges)) {
    const el = document.querySelector(`[data-badge="${id}"]`);
    if (el) { el.textContent = count ? String(count) : ""; el.className = `nav-badge ${cls}`; }
  }

  renderWatch(s);
  $("#rail-version").textContent = `v${app.config?.version || "?"}`;
  $("#rail-source").textContent = `${s.sources.filter((x) => x.present).length}/${s.sources.length} sources`;
  renderTaskbar();
}

function renderWatch(s) {
  const body = $("#watch-body");
  const a = s.agents;
  const rows = [
    ["productive", a.working, "var(--green)"],
    ["idle · no lease", a.idle, "var(--blue)"],
    ["blocked", a.blocked, "var(--red)"],
    ["stalled", a.stalled, "var(--signal)"],
    ["retired", a.retired, "var(--ink-4)"],
  ];
  const alerts = s.alerts || [];
  const el = h("div", { style: { display: "grid", gap: "10px" } },
    h("div", { class: "watch-block" },
      h("div", { class: "label", style: { marginBottom: "4px" } }, "Accountability"),
      ...rows.map(([k, v, c]) => h("div", { class: "account-row" },
        h("div", { class: "account-k" }, h("span", { class: "account-dot", style: { background: c } }), k),
        h("div", { class: "account-v", text: String(v) })))),
    h("div", { class: "watch-block" },
      h("div", { class: "label", style: { marginBottom: "6px" } }, `Alerts · ${alerts.length}`),
      alerts.length
        ? h("div", { style: { display: "grid", gap: "6px" } }, ...alerts.slice(0, 5).map((al) =>
          h("div", { class: "alert", dataset: { sev: al.severity } },
            h("div", { class: "alert-head" }, h("span", { class: "alert-kind", text: al.kind })),
            h("div", { text: al.text }),
            al.refs ? h("div", { class: "alert-refs" }, ...al.refs.slice(0, 5).map((r) =>
              h("button", { onclick: () => openTask(r), text: r }))) : null)))
        : h("div", { class: "watch-empty" }, "Nothing out of order. That is not the same as nothing to do.")),
    h("div", { class: "law" },
      h("div", { class: "label", style: { marginBottom: "5px" } }, "Standing law"),
      h("p", {}, h("b", {}, "45 minutes"), " of board silence is a death. Leases expire; the card returns to the pool."),
      h("p", {}, h("b", {}, "No block without a reason"), " recorded on the card."),
      h("p", {}, h("b", {}, "No self-approval."), " Two inspected, non-owner accept votes close work."),
      h("p", {}, h("b", {}, "Unpushed is undone."), " The archive outlives the operative.")),
  );
  body.replaceChildren(el);
  const src = s.sources.filter((x) => x.present);
  $("#watch-foot").replaceChildren(
    h("div", { text: `data as of ${(s.generated_ts || "").replace("T", " ").slice(0, 19)}Z` }),
    h("div", { text: src.map((x) => `${x.name}@${x.head}`).join("  ") }),
    h("div", { text: `version ${s.version}` }),
  );
}

function renderTaskbar() {
  const host = $("#tb-windows");
  if (!host) return;
  const wins = Array.from(app.wm.wins.entries());
  host.replaceChildren(...wins.map(([id, w]) => h("button", {
    class: "tb-win",
    dataset: { active: String(app.wm.focused === id && !w.state.min) },
    onclick: () => app.wm.restore(id),
    title: `Alt+click to close`,
  }, h("span", { class: "dot" }), w.view.title)));
  for (const nav of document.querySelectorAll(".nav-item")) {
    nav.setAttribute("aria-current", String(app.wm.focused === nav.dataset.view));
  }
}

async function pollResources() {
  try {
    const r = await api.resources();
    const el = $("#tb-mem");
    if (el) el.textContent = `${r.agencyos.rss_mb} MB`;
    const el2 = $("#tb-silence");
    if (el2 && app.summary) el2.textContent = `silence ${silenceText(app.summary)}`;
  } catch { /* daemon busy */ }
}

function silenceText(s) {
  const ts = s.last_activity_ts || s.wire.last_ts;
  if (!ts) return "unknown";
  const d = parseTs(ts);
  if (!d) return "unknown";
  return fmtAge((Date.now() - d.getTime()) / 60000);
}

function tickClock() {
  const now = new Date();
  $("#clock-utc").textContent = fmtClock(now);
  $("#clock-local").textContent = `${now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} local`;
  $("#tb-clock").textContent = fmtClock(now, false);
  if (app.summary) {
    const el = $("#tb-silence");
    if (el) el.textContent = `silence ${silenceText(app.summary)}`;
  }
}

/* ------------------------------------------------------------------- live */
function startLive() {
  subscribe(
    debounce(async (msg) => {
      try {
        const s = await api.summary();
        app.summary = s;
        renderChrome(s);
        document.dispatchEvent(new CustomEvent("agency:change", { detail: msg }));
        if (window.__paletteOpen) runPaletteSearch($("#palette-input")?.value || "");
      } catch (err) {
        setConn("down");
      }
    }, 300),
    (status) => setConn(status),
  );
}

function setConn(state) {
  app.conn = state;
  const el = $("#conn");
  if (!el) return;
  el.dataset.state = state;
  el.textContent = state === "live" ? "linked" : state === "down" ? "reconnecting" : "linking";
}

async function pollSummary() {
  try {
    const s = await api.summary();
    app.summary = s;
    renderChrome(s);
    setConn("live");
  } catch {
    setConn("down");
  }
}

/* ------------------------------------------------------------------ views */
function openView(id) {
  const v = VIEWS[id] || VIEWS.overview;
  app.wm.open(id in VIEWS ? id : "overview", v);
  if (history.replaceState) history.replaceState(null, "", `#${id in VIEWS ? id : "overview"}`);
  renderTaskbar();
}

function openTask(id) {
  if (!id) return;
  app.wm.open("board", board);
  setTimeout(() => document.dispatchEvent(new CustomEvent("agency:open-task", { detail: id })), 30);
}

function openAgent(name) {
  if (!name) return;
  app.wm.open("agents", agents);
  setTimeout(() => document.dispatchEvent(new CustomEvent("agency:open-agent", { detail: name })), 30);
}

// Deep links and the browser's back/forward buttons: the hash is the route.
// openView() writes it with replaceState, which does not fire this event, so no loop.
window.addEventListener("hashchange", () => {
  const id = (location.hash || "#overview").slice(1);
  if (!id) return;
  openView(id);
});

bus.addEventListener("open:task", (e) => openTask(e.detail));
bus.addEventListener("open:agent", (e) => openAgent(e.detail));
bus.addEventListener("navigate", (e) => openView(e.detail));

window.addEventListener("agency:reset-layout", () => app.wm.resetLayout());

/* ----------------------------------------------------------------- palette */
function buildPalette() {
  const scrim = h("div", { class: "scrim", id: "scrim", hidden: true, onclick: (e) => {
    if (e.target.id === "scrim") closePalette();
  } },
    h("div", { class: "palette", role: "dialog", "aria-label": "Command palette" },
      h("input", { class: "palette-input", id: "palette-input", placeholder: "Jump to a panel, a card, an operative…", autocomplete: "off" }),
      h("div", { class: "palette-list", id: "palette-list" }),
      h("div", { class: "palette-foot" },
        h("span", {}, h("kbd", {}, "↑↓"), " navigate"),
        h("span", {}, h("kbd", {}, "↵"), " open"),
        h("span", {}, h("kbd", {}, "esc"), " dismiss"),
        h("span", { style: { marginLeft: "auto" } }, "every result is read from the mirrors"))));
  document.body.appendChild(scrim);
  const input = $("#palette-input", scrim);
  input.addEventListener("input", debounce((e) => runPaletteSearch(e.target.value), 160));
  input.addEventListener("keydown", paletteKeys);
  scrim.addEventListener("keydown", paletteKeys);
  scrim._index = 0;
  scrim._items = [];
}

const COMMANDS = [
  ["Overview", "open the agency's front page", () => openView("overview")],
  ["Agent registry", "every operative and their accountability", () => openView("agents")],
  ["Board", "the task queue", () => openView("board")],
  ["Communications", "the bus", () => openView("comms")],
  ["Review queue", "cards waiting for ballots", () => openView("review")],
  ["Repositories", "mirrors and the GitHub estate", () => openView("repos")],
  ["Records", "ledger, shifts, wire", () => openView("records")],
  ["Resources", "measured memory and process tree", () => openView("resources")],
  ["Settings", "configuration and write access", () => openView("settings")],
  ["Sync mirrors", "git fetch --ff-only on every source", async () => {
    const res = await fetch("/api/sync", { method: "POST", headers: { "X-AgencyOS": "1" } });
    const data = await res.json();
    toast(res.ok ? "Mirrors synced" : "Sync failed",
      (data.report || []).map((r) => `${r.name}:${r.action}`).join(" · ") || data.error, res.ok ? "ok" : "error", 4200);
  }],
  ["Toggle theme", "graphite / paper", () => {
    const cur = document.documentElement.dataset.theme === "paper" ? "graphite" : "paper";
    document.documentElement.dataset.theme = cur;
    localStorage.setItem("agencyos.theme", cur);
  }],
];

function openPalette() {
  const scrim = $("#scrim");
  scrim.hidden = false;
  window.__paletteOpen = true;
  const input = $("#palette-input");
  input.value = "";
  input.focus();
  runPaletteSearch("");
}

function closePalette() {
  $("#scrim").hidden = true;
  window.__paletteOpen = false;
}

async function runPaletteSearch(q) {
  const list = $("#palette-list");
  const scrim = $("#scrim");
  const query = (q || "").trim();
  const items = [];
  for (const [title, sub, fn] of COMMANDS) {
    if (!query || title.toLowerCase().includes(query.toLowerCase())) items.push({ kind: "panel", title, sub, fn });
  }
  if (query.length >= 2) {
    try {
      const res = await api.search(query);
      for (const t of res.tasks.slice(0, 6)) items.push({ kind: "card", title: t.title, sub: `${t.id} · ${t.status}`, fn: () => openTask(t.id) });
      for (const a of res.agents.slice(0, 4)) items.push({ kind: "agent", title: a.name, sub: `${a.role} · ${a.state}`, fn: () => openAgent(a.name) });
    } catch { /* search is optional */ }
  }
  scrim._items = items;
  scrim._index = clamp(scrim._index || 0, 0, Math.max(0, items.length - 1));
  list.replaceChildren(...items.map((it, i) => h("div", {
    class: "palette-item", "aria-selected": String(i === scrim._index),
    onclick: () => { closePalette(); it.fn(); },
    onmouseenter: () => { scrim._index = i; markPalette(); },
  }, h("span", { class: "grp", text: it.kind }), h("span", { class: "truncate", text: it.title }),
    h("span", { class: "k truncate", text: it.sub }))));
  if (!items.length) list.replaceChildren(h("div", { class: "vlist-empty" }, "No match in panels, cards or the roster."));
}

function markPalette() {
  const scrim = $("#scrim");
  Array.from($("#palette-list").children).forEach((el, i) =>
    el.setAttribute("aria-selected", String(i === scrim._index)));
}

function paletteKeys(e) {
  const scrim = $("#scrim");
  if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = scrim._items.length;
    if (!n) return;
    scrim._index = (scrim._index + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    markPalette();
    const el = $("#palette-list").children[scrim._index];
    el?.scrollIntoView({ block: "nearest" });
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    const it = scrim._items[scrim._index];
    if (it) { closePalette(); it.fn(); }
  }
}

/* ------------------------------------------------------------------- keys */
function bindKeys() {
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      window.__paletteOpen ? closePalette() : openPalette();
      return;
    }
    if (e.altKey && /^[1-9]$/.test(e.key)) {
      const id = Object.keys(VIEWS)[Number(e.key) - 1];
      if (id) { e.preventDefault(); openView(id); }
    }
    if (e.key === "Escape" && window.__paletteOpen) closePalette();
  });
}

boot();
