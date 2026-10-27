// overview.js — the agency's front page: state, directive, next action, activity.
import { api } from "../api.js";
import {
  h, icon, fmtAge, fmtDate, ago, VirtualList, codeBlock, toast, copyText,
} from "../util.js";
import { navigate, openAgent, openTask, sectionTitle, emptyState, gridHead } from "./common.js";

const KIND_ICON = { wire: "wire", push: "push", task: "task", shift: "shift" };

export const overview = {
  id: "overview",
  title: "Agency overview",
  icon: "overview",
  size: [1020, 660],
  mount(body, { signal, sub }) {
    const hero = h("div", { class: "hero" });
    const directive = h("div", { class: "section" });
    const boardPanel = h("div", { class: "section" });
    const actions = h("div", { class: "section" });
    const feed = h("div", { class: "section", style: { padding: "10px 0 0" } });
    const feedHead = h("div", { style: { padding: "0 12px" } });

    const scroll = h("div", { class: "pane-scroll" },
      hero,
      h("div", { class: "cols-2" }, directive, boardPanel),
      actions,
      feed,
    );
    body.append(scroll);

    const list = new VirtualList({
      rowHeight: 40,
      row: (ev) => h("div", { class: "tl-row", dataset: { kind: ev.kind } },
        h("div", { class: "tl-time mono", text: (ev.ts || "").slice(11, 16) }),
        h("div", { class: "tl-dot" }),
        h("div", { class: "tl-body" },
          h("div", { class: "tl-meta" },
            h("span", { class: "tl-actor", text: ev.actor || "—" }),
            ev.repo ? h("span", { class: "tl-repo", text: ev.repo }) : null,
            h("span", { class: "tl-repo", text: ev.kind }),
          ),
          h("div", { class: "truncate", style: { maxWidth: "100%" }, title: ev.text, text: ev.text }),
        ),
      ),
      empty: "No recorded activity in the sources.",
    });
    feed.append(feedHead, list.el);
    list.el.style.height = "430px";

    let last = null;
    async function refresh() {
      if (!body.isConnected) return;
      try {
        const s = await api.summary();
        last = s;
        renderHero(s);
        renderDirective(s);
        renderBoard(s);
        renderActions(s);
        sub(`${s.board.total} cards · ${s.agents.total} operatives · v${s.version}`);
        const act = await api.activity({ limit: 300 });
        list.setRows(act.events);
        feedHead.replaceChildren(
          h("div", { style: { display: "flex", alignItems: "baseline", gap: "10px", paddingBottom: "6px" } },
            sectionTitle("Everything that moved", h("span", { class: "label", style: { color: "var(--ink-4)" } }, "unified log · wire + ledger + board + shifts")),
          ),
        );
      } catch (err) {
        if (body.isConnected) {
          body.replaceChildren(emptyState("The deck cannot reach agencyd",
            `The daemon stopped answering: ${err.message}. The data on screen would be a lie, so it is not shown.`));
        }
      }
    }

    function renderHero(s) {
      const st = s.status;
      hero.replaceChildren(
        h("div", { class: "hero-corner" }),
        h("div", { class: "label", style: { marginBottom: "6px" } }, "Organisation state"),
        h("div", { class: "hero-status", dataset: { code: st.code }, text: st.label }),
        h("div", { class: "hero-detail", text: st.detail }),
        h("div", { class: "hero-stats" },
          stat(s.agents.alive, `alive / ${s.agents.total}`),
          stat(s.board.live, "live cards"),
          stat(s.board.review, "awaiting review"),
          stat(s.leases.expired, "expired leases"),
          stat(s.wire.last_24h, "wire · 24h"),
        ),
        h("div", { style: { marginTop: "12px", display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" } },
          h("button", { class: "btn ghost", onclick: () => navigate("board") }, icon("board", 12), "Open the board"),
          h("button", { class: "btn ghost", onclick: () => navigate("agents") }, icon("agents", 12), "Roster"),
          h("button", { class: "btn ghost", onclick: () => navigate("review") }, icon("review", 12), `Review queue · ${s.board.review}`),
          s.orders.epoch ? h("span", { class: "tag", style: { marginLeft: "auto" } }, `DIRECTIVE EPOCH ${s.orders.epoch}`) : null,
        ),
      );
    }

    function stat(v, k) {
      return h("div", { class: "hero-stat" },
        h("div", { class: "v", text: String(v ?? "—") }),
        h("div", { class: "k", text: k }));
    }

    function renderDirective(s) {
      const orders = s.orders;
      directive.replaceChildren(
        h("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" } },
          sectionTitle("Directive in force"),
          orders.present ? h("span", { class: "tag sig", text: orders.epoch || "no epoch" }) : h("span", { class: "tag", text: "not found" }),
        ),
        orders.standing.length
          ? h("ol", { class: "orders" }, ...orders.standing.map((t) => h("li", { html: mdInline(t) })))
          : h("div", { class: "dim", style: { fontSize: "12px" } },
            "No ORDERS.md was found in the agency mirror. Standing orders are the only place a directive may live."),
        orders.redlines && orders.redlines.length
          ? h("details", { style: { marginTop: "8px" } },
            h("summary", { class: "label", style: { cursor: "pointer" } }, `Red lines · ${orders.redlines.length}`),
            h("ul", { class: "orders redlines" }, ...orders.redlines.map((t) => h("li", { html: mdInline(t) }))))
          : null,
      );
    }

    function renderBoard(s) {
      const b = s.board;
      const total = Math.max(1, b.open + b.claimed + b.review + b.blocked + b.done + b.dropped);
      const seg = (n, cls) => h("i", { class: cls, style: { width: `${(n / total) * 100}%` } });
      boardPanel.replaceChildren(
        sectionTitle("Board composition"),
        h("div", { class: "bar", style: { height: "8px", marginBottom: "10px" } },
          seg(b.open, "bg-open"), seg(b.claimed, "bg-claimed"), seg(b.review, "bg-review"),
          seg(b.blocked, "bg-blocked"), seg(b.done, "bg-done"), seg(b.dropped, "bg-dropped")),
        h("div", { class: "board-counts" },
          countRow("open", b.open, () => navigate("board")),
          countRow("claimed", b.claimed, () => navigate("board")),
          countRow("review", b.review, () => navigate("review")),
          countRow("blocked", b.blocked, () => navigate("board")),
          countRow("done", b.done, () => navigate("board")),
          countRow("dropped", b.dropped, () => navigate("board")),
        ),
        h("div", { class: "label", style: { marginTop: "12px" } }, "Agency jobs"),
        h("div", { class: "dim", style: { fontSize: "11.5px" } },
          `${s.jobs.total} briefed · ${s.jobs.claimed} claimed · ${s.jobs.open} open — contracts live in agency/jobs/`),
      );
    }

    function countRow(name, n, fn) {
      return h("button", { class: "board-count", onclick: fn },
        h("i", { class: `bg-${name}` }),
        h("span", { text: name }),
        h("b", { class: "mono", text: String(n) }));
    }

    function renderActions(s) {
      const acts = s.next_actions || [];
      const alerts = s.alerts || [];
      actions.replaceChildren(
        sectionTitle("What has to happen next"),
        alerts.length
          ? h("div", { class: "alert-strip" }, ...alerts.slice(0, 3).map((a) =>
            h("div", { class: "alert", dataset: { sev: a.severity } },
              h("div", { class: "alert-head" }, icon(a.severity === "critical" ? "alert" : "eye", 11),
                h("span", { class: "alert-kind", text: a.kind })),
              h("div", { text: a.text }),
              a.refs ? h("div", { class: "alert-refs" }, ...a.refs.slice(0, 8).map((r) =>
                h("button", { onclick: () => openTask(r), text: r }))) : null)))
          : h("div", { class: "dim", style: { fontSize: "12px", marginBottom: "10px" } },
            "No alerts. Every operative accounted for, every lease inside its clock."),
        h("div", { class: "actions" }, ...acts.map((a) =>
          h("div", { class: "action" },
            h("div", { class: "action-pri", text: String(a.priority) }),
            h("div", { class: "action-body" },
              h("div", { class: "action-title", text: a.title }),
              h("div", { class: "action-detail", text: a.detail }),
              a.command ? h("div", { class: "action-cmd" }, codeBlock(a.command)) : null),
          ))),
      );
    }

    refresh();
    document.addEventListener("agency:change", refresh, { signal });
  },
};

function mdInline(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}
