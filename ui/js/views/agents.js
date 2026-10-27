// agents.js — the registry. Every operative, accounted for or not.
import { api } from "../api.js";
import { h, icon, fmtAge, ago, VirtualList, codeBlock, fmtDate } from "../util.js";
import {
  agentChip, statusChip, sectionTitle, emptyState, openTask, kvList, markdown, timeCell,
} from "./common.js";

const STATE_ORDER = ["working", "idle", "blocked", "stalled", "retired", "unknown"];

export const agents = {
  id: "agents",
  title: "Agent registry",
  icon: "agents",
  size: [1000, 640],
  mount(body, { signal, sub }) {
    let all = [];
    let selected = null;
    let filter = "all";
    let query = "";

    const list = new VirtualList({
      rowHeight: 46,
      className: "agent-list",
      row: (a) => {
        const el = h("div", {
          class: "agent-row",
          dataset: { selected: String(a.name === selected), state: a.state },
          onclick: () => select(a.name),
        },
          h("span", { class: "agent-dot" }),
          h("div", { style: { minWidth: 0 } },
            h("div", { class: "agent-name" }, a.display || a.name,
              a.role === "lead" ? h("span", { class: "tag sig", style: { marginLeft: "6px" } }, "LEAD") : null,
              a.kind === "human" ? h("span", { class: "tag", style: { marginLeft: "6px" } }, "HUMAN") : null),
            h("div", { class: "agent-sub truncate", text: a.model || a.role || a.kind }),
          ),
          h("div", { class: "agent-right" },
            h("span", { class: `chip st-${a.state}`, style: { fontSize: "8.5px" } }, shortState(a.state)),
            h("span", { class: "mono", style: { fontSize: "9.5px", color: "var(--ink-4)" }, text: a.silence })),
        );
        return el;
      },
      empty: "No operatives match this filter.",
    });

    const detail = h("div", { class: "pane-scroll" });
    const search = h("input", {
      class: "input", placeholder: "Filter by name, capability, model…", style: { width: "100%" },
      oninput: (e) => { query = e.target.value.toLowerCase(); renderList(); },
    });
    const seg = h("div", { class: "seg" },
      ...[["all", "All"], ["alive", "Alive"], ["blocked", "Blocked"], ["retired", "Retired"]].map(([k, label]) =>
        h("button", { dataset: { k }, "aria-pressed": String(k === filter), onclick: (e) => {
          filter = k;
          for (const b of seg.children) b.setAttribute("aria-pressed", String(b.dataset.k === k));
          renderList();
        } }, label)));

    const left = h("div", { class: "col", style: { background: "var(--bg-2)" } },
      h("div", { class: "pane-head", style: { gap: "6px" } }, search),
      h("div", { class: "pane-head", style: { paddingTop: 0, borderTop: 0 } }, seg),
      list.el,
    );
    body.append(h("div", { class: "split" }, left, h("div", { class: "col" }, detail)));

    function renderList() {
      let rows = all;
      if (filter === "alive") rows = rows.filter((a) => ["working", "idle", "blocked", "stalled"].includes(a.state));
      if (filter === "blocked") rows = rows.filter((a) => a.state === "blocked" || a.blocked.length);
      if (filter === "retired") rows = rows.filter((a) => a.state === "retired");
      if (query) {
        rows = rows.filter((a) => `${a.name} ${a.display} ${a.caps} ${a.model} ${a.role}`.toLowerCase().includes(query));
      }
      rows = [...rows].sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state));
      list.setRows(rows);
    }

    async function select(name) {
      selected = name;
      renderList();
      detail.replaceChildren(h("div", { class: "empty", text: "Reading the file…" }));
      try {
        const a = await api.agent(name);
        if (!body.isConnected || selected !== name) return;
        detail.replaceChildren(renderDetail(a));
      } catch (err) {
        detail.replaceChildren(emptyState("Cannot read this operative", err.message));
      }
    }

    function renderDetail(a) {
      const frag = document.createDocumentFragment();
      const parts = [
        h("div", { class: "agent-head" },
          h("div", { style: { minWidth: 0 } },
            h("div", { class: "label" }, "Operative"),
            h("h2", { class: "agent-title", text: (a.display || a.name).toUpperCase() }),
            h("div", { class: "mono dim", style: { fontSize: "10.5px" } }, a.name)),
          h("div", { style: { marginLeft: "auto", textAlign: "right", display: "grid", gap: "4px", justifyItems: "end" } },
            agentChip(a.state),
            h("span", { class: "tag", text: a.life_clock }),
            h("span", { class: "mono faint", style: { fontSize: "10px" } }, `silence ${a.silence}`)),
        ),
        h("div", { class: "section" },
          kvList([
            ["role", a.role || "—"],
            ["kind", a.kind || "—"],
            ["model", a.model || "—"],
            ["caps", a.caps || "—"],
            ["source", (a.sources || []).join(" + ") || "—"],
            ["joined", a.joined_ts ? fmtDate(a.joined_ts, { time: true }) : "—"],
            ["last seen", a.last_seen ? `${fmtDate(a.last_seen, { time: true })} · ${ago(a.last_seen)} ago` : "never"],
            ["epoch", a.epoch || "—"],
            ["note", a.note || "—"],
          ])),
        accountability(a),
        heldBlock(a),
        tasksBlock(a),
        shiftBlock(a),
        heartbeatBlock(a),
        messageBlock(a),
      ];
      for (const p of parts) if (p) frag.append(p);
      return frag;
    }

    function accountability(a) {
      const stateText = {
        working: "Holds a live lease. Productive work is visible on the board.",
        idle: "Awake and unassigned. Doctrine: claim the next approved card or report that you need one.",
        blocked: "Blocked. A block must carry a written reason; a silent stall is a protocol violation.",
        stalled: "No board write inside the 45-minute window. Presumed dead until proven otherwise.",
        retired: "No sign of life for hours. The archive outlives the operative; the card returns to the pool.",
        unknown: "No timestamp anywhere. Unaccounted for.",
      }[a.state] || "";
      return h("div", { class: "section" },
        sectionTitle("Accountability"),
        h("div", { class: `accountability state-${a.state}` },
          h("div", { class: "acc-line", text: stateText }),
          a.blocked.length
            ? h("div", { style: { marginTop: "8px", display: "grid", gap: "4px" } },
              ...a.blocked.map((b) => h("div", { class: "acc-block" },
                h("span", { class: "label", style: { color: "var(--red)" } }, "blocked"),
                h("span", { class: "mono", style: { fontSize: "10px" } }, b.id),
                h("span", { class: "dim", text: b.reason }))))
            : null,
          a.lease_expired
            ? h("div", { class: "acc-warn" }, icon("alert", 11),
              " Holds an expired lease — a sweep returns it to the open pool.")
            : null,
        ));
    }

    function heldBlock(a) {
      if (!a.held.length) return h("div", { class: "section" },
        sectionTitle("Held cards"),
        h("div", { class: "dim", style: { fontSize: "11.5px" } }, "Nothing held. No lease, no custody, no collision."));
      return h("div", { class: "section" },
        sectionTitle("Held cards", h("span", { class: "label" }, `${a.held.length}`)),
        h("div", { style: { display: "grid", gap: "5px" } },
          ...a.held.map((t) => h("div", { class: "held", onclick: () => openTask(t.id) },
            statusChip(t.status),
            h("span", { class: "mono", style: { fontSize: "10px", color: "var(--ink-4)" } }, t.id),
            h("span", { class: "truncate", style: { flex: 1 }, text: t.title }),
            t.lease?.expires
              ? h("span", { class: "mono faint", style: { fontSize: "9.5px" } },
                `lease ${new Date(t.lease.expires) > new Date() ? "until" : "expired"} ${fmtDate(t.lease.expires, { time: true })}`)
              : null))));
    }

    function tasksBlock(a) {
      if (!a.tasks?.length) return null;
      return h("div", { class: "section" },
        sectionTitle("Recent cards", h("span", { class: "label" }, `${a.tasks.length}`)),
        h("div", { class: "mini-table" },
          ...a.tasks.slice(0, 12).map((t) => h("div", { class: "mini-row", onclick: () => openTask(t.id) },
            statusChip(t.status),
            h("span", { class: "mono", style: { fontSize: "10px", color: "var(--ink-4)" } }, t.id),
            h("span", { class: "truncate", style: { flex: 1 }, text: t.title }),
            h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, ago(t.updated_ts))))));
    }

    function shiftBlock(a) {
      if (!a.shifts?.length) return null;
      return h("div", { class: "section" },
        sectionTitle("Shift notes", h("span", { class: "label" }, `${a.shifts.length}`)),
        h("div", { style: { display: "grid", gap: "6px" } },
          ...a.shifts.slice(0, 6).map((s) => h("details", { class: "shift" },
            h("summary", {},
              h("span", { class: "mono", style: { fontSize: "10px", color: "var(--ink-4)" } }, s.date),
              h("span", { text: s.title }),
            ),
            h("div", { class: "md-wrap" }, markdown(s.body.slice(0, 6000)),
              h("a", { href: s.url, target: "_blank", rel: "noopener", class: "ext" }, "source on GitHub"))))));
    }

    function heartbeatBlock(a) {
      if (!a.heartbeats?.length) return null;
      return h("div", { class: "section" },
        sectionTitle("Heartbeats", h("span", { class: "label" }, `${a.heartbeats.length} pulses`)),
        h("div", { class: "hb" }, ...a.heartbeats.slice(-10).reverse().map((hb) =>
          h("div", { class: "hb-row" },
            h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, (hb.ts || "").replace("T", " ").slice(0, 16)),
            h("span", { class: "tag", text: hb.kind || "pulse" }),
            h("span", { class: "dim truncate", text: hb.note || "" })))));
    }

    function messageBlock(a) {
      if (!a.messages?.length) return null;
      return h("div", { class: "section" },
        sectionTitle("Last words on the bus"),
        h("div", { style: { display: "grid", gap: "6px" } }, ...a.messages.slice(0, 6).map((m) =>
          h("div", { class: "quote" },
            h("div", { class: "label" }, `${(m.ts || "").slice(0, 16).replace("T", " ")} · ${m.type || "say"} · #${m.channel}`),
            h("div", { class: "quote-text", text: (m.text || "").slice(0, 420) })))));
    }

    async function refresh() {
      if (!body.isConnected) return;
      try {
        const data = await api.agents();
        all = data.agents;
        const alive = all.filter((a) => ["working", "idle", "blocked"].includes(a.state)).length;
        sub(`${alive} alive / ${all.length} · ${all.filter((a) => a.state === "working").length} productive`);
        renderList();
        if (!selected && all.length) select(all[0].name);
        else if (selected) {
          const fresh = all.find((a) => a.name === selected);
          if (fresh && detail.childElementCount) {
            // cheap re-render of the detail header only when the state changed
            const chipEl = detail.querySelector(".agent-head .chip");
            if (chipEl && chipEl.className !== `chip st-${fresh.state}`) select(selected);
          }
        } else if (!all.length) {
          detail.replaceChildren(emptyState("No roster", "No agents/*.json was found in the mirrors."));
        }
      } catch (err) {
        detail.replaceChildren(emptyState("Registry unavailable", err.message));
      }
    }

    refresh();
    document.addEventListener("agency:change", refresh, { signal });
    document.addEventListener("agency:open-agent", (e) => {
      if (e.detail) select(e.detail);
    }, { signal });
  },
};

function shortState(s) {
  return { working: "PRODUCTIVE", idle: "IDLE", blocked: "BLOCKED", stalled: "STALLED", retired: "RETIRED", unknown: "UNKNOWN" }[s] || s;
}
