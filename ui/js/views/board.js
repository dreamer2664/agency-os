// board.js — the work queue. One card per task, one owner, no collisions.
import { api, action } from "../api.js";
import {
  h, icon, fmtAge, ago, fmtDate, VirtualList, codeBlock, toast, STATUS_LABEL,
} from "../util.js";
import {
  statusChip, sectionTitle, emptyState, gridHead, applyGrid, TASK_COLUMNS, taskRow, openTask, kvList, markdown,
} from "./common.js";

const FILTERS = ["open", "claimed", "review", "blocked", "done", "dropped", "all"];

export const board = {
  id: "board",
  title: "Board",
  icon: "board",
  size: [1080, 660],
  mount(body, { signal, sub }) {
    let tab = "tasks";
    let status = "open";
    let q = "";
    let counts = {};
    let jobs = [];
    let selected = null;
    let writeMode = false;

    const segTab = h("div", { class: "seg" },
      tabBtn("tasks", "Chatcode board"), tabBtn("jobs", "Agency jobs"));
    const segStatus = h("div", { class: "seg", style: { marginLeft: "4px" } });
    const search = h("input", { class: "input", placeholder: "Search cards…", style: { width: "210px" },
      oninput: (e) => { q = e.target.value; refreshList(); } });
    const countLabel = h("span", { class: "count" });
    const head = h("div", { class: "pane-head" }, segTab, segStatus, search, countLabel,
      h("span", { style: { flex: 1 } }),
      h("span", { class: "label", id: "board-mode" }));
    const gridHeadEl = h("div");
    const bodyEl = h("div", { class: "grid-scroll" });
    const drawer = h("aside", { class: "drawer", hidden: true });
    const main = h("div", { class: "board-main" }, head, gridHeadEl, bodyEl);
    body.append(h("div", { class: "board-wrap" }, main, drawer));

    const list = new VirtualList({
      rowHeight: 31,
      className: "grid-body",
      row: (t) => {
        const el = taskRow(t, (id) => showTask(id));
        el.dataset.selected = String(t.id === selected);
        return applyGrid(el, TASK_COLUMNS);
      },
      empty: "No cards in this view.",
    });
    bodyEl.appendChild(list.el);
    list.el.style.height = "100%";

    function tabBtn(k, label) {
      return h("button", { dataset: { k }, "aria-pressed": String(k === tab), onclick: () => {
        tab = k;
        for (const b of segTab.children) b.setAttribute("aria-pressed", String(b.dataset.k === k));
        renderStatusSeg();
        refreshList();
      } }, label);
    }

    function renderStatusSeg() {
      segStatus.replaceChildren();
      if (tab !== "tasks") { segStatus.style.display = "none"; return; }
      segStatus.style.display = "";
      for (const f of FILTERS) {
        segStatus.appendChild(h("button", { "aria-pressed": String(status === f), onclick: () => {
          status = f;
          renderStatusSeg();
          refreshList();
        } }, `${f}${counts[f] !== undefined ? ` ${counts[f]}` : ""}`));
      }
    }

    function renderHead() {
      if (tab === "tasks") {
        gridHeadEl.replaceChildren(gridHead(TASK_COLUMNS));
      } else {
        gridHeadEl.replaceChildren(gridHead([
          { label: "status", width: "96px" }, { label: "job", width: "230px" },
          { label: "title", width: "1fr" }, { label: "owner", width: "100px" },
          { label: "phase", width: "70px" }, { label: "evidence", width: "74px", num: true },
          { label: "updated", width: "86px", num: true },
        ]));
      }
    }

    async function refreshList() {
      if (!body.isConnected) return;
      if (tab === "tasks") {
        const data = await api.tasks({ status, q, limit: 500 });
        counts = data.counts;
        countLabel.textContent = `${data.total} card${data.total === 1 ? "" : "s"}`;
        sub(`${data.counts.live} live · ${data.counts.review} in review`);
        renderStatusSeg();
        list.setRows(data.tasks);
      } else {
        const data = await api.jobs();
        jobs = data.jobs;
        countLabel.textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"}`;
        sub(`${jobs.filter((j) => j.status === "claimed").length} claimed`);
        const jobCols = [
          { width: "92px" }, { width: "216px" }, { width: "minmax(0, 1fr)" },
          { width: "96px" }, { width: "62px" }, { width: "68px", num: true },
          { width: "74px", num: true },
        ];
        const v = new VirtualList({
          rowHeight: 40, className: "grid-body",
          row: (j) => h("div", { class: "grid-row", onclick: () => showJob(j.id) },
            h("div", { class: "cell" }, statusChip(j.status)),
            h("div", { class: "cell mono", style: { fontSize: "10px", color: "var(--ink-4)" } }, j.id),
            h("div", { class: "cell truncate" }, j.title),
            h("div", { class: "cell", style: { color: "var(--ink-3)" } }, j.owner || "—"),
            h("div", { class: "cell mono", style: { fontSize: "10px" } }, j.phase || "—"),
            h("div", { class: "cell num" }, String(j.evidence.length)),
            h("div", { class: "cell num", style: { color: "var(--ink-4)" } }, ago(j.updated_ts))),
          empty: "No job briefs in agency/jobs/.",
        });
        const orig = v.row;
        v.row = (r, i) => applyGrid(orig(r, i), jobCols);
        v.setRows(jobs);
        bodyEl.replaceChildren(v.el);
        v.el.style.height = "100%";
        list.setRows([]);
      }
    }

    async function showTask(id) {
      selected = id;
      drawer.hidden = false;
      drawer.className = "drawer open";
      drawer.replaceChildren(h("div", { class: "drawer-loading", text: "Reading card…" }));
      try {
        const t = await api.task(id);
        drawer.replaceChildren(renderTask(t));
      } catch (err) {
        drawer.replaceChildren(emptyState("Cannot read this card", err.message));
      }
      refreshList();
    }

    async function showJob(id) {
      selected = id;
      drawer.hidden = false;
      drawer.className = "drawer open";
      try {
        const j = await api.job(id);
        drawer.replaceChildren(renderJob(j));
      } catch (err) {
        drawer.replaceChildren(emptyState("Cannot read this job", err.message));
      }
    }

    function closeDrawer() {
      drawer.hidden = true;
      drawer.className = "drawer";
      selected = null;
      refreshList();
    }

    // Escape closes the drawer, as it does in every other overlay in the deck.
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !drawer.hidden && !window.__paletteOpen) {
        e.stopPropagation();
        closeDrawer();
      }
    }, { signal });

    function drawerHead(kicker, title, chipEl) {
      return h("div", { class: "drawer-head" },
        h("div", { style: { minWidth: 0, flex: 1 } },
          h("div", { class: "label" }, kicker),
          h("h3", { class: "drawer-title", text: title || "(untitled)" })),
        chipEl,
        h("button", { class: "win-btn", onclick: closeDrawer, title: "Close" }, icon("close", 12)));
    }

    function renderTask(t) {
      const frag = document.createDocumentFragment();
      const lease = t.lease || null;
      const active = lease?.expires && new Date(lease.expires) > new Date();
      frag.append(
        drawerHead(t.id, t.title, statusChip(t.status)),
        h("div", { class: "drawer-body" },
          h("div", { class: "drawer-actions" },
            h("button", {
              class: "btn primary", disabled: !writeMode || t.status !== "open",
              title: writeMode ? "" : "write mode is off",
              onclick: () => runAction("claim", { id: t.id }),
            }, icon("bolt", 12), "Claim"),
            h("button", { class: "btn", onclick: () => copyCmd(`python3 bin/chatcode tasks claim ${t.id} --announce`) },
              icon("copy", 12), "Copy claim"),
            t.pr ? h("a", { class: "btn", href: t.pr, target: "_blank", rel: "noopener" }, icon("external", 12), `PR #${String(t.pr).split("/").pop()}`) : null,
            h("button", { class: "btn ghost", onclick: () => copyCmd(`python3 bin/chatcode tasks show ${t.id}`) }, "show"),
          ),
          kvList([
            ["status", STATUS_LABEL[t.status] || t.status],
            ["owner", t.owner || "unclaimed"],
            ["priority", t.priority],
            ["created", `${fmtDate(t.created_ts, { time: true })} by ${t.created_by || "—"}`],
            ["updated", `${fmtDate(t.updated_ts, { time: true })} · ${ago(t.updated_ts)} ago`],
            ["branch", t.branch ? h("span", { class: "mono", text: t.branch }) : "—"],
            ["parent", t.parent || "—"],
            ["tags", (t.tags || []).join(", ") || "—"],
            ["deps", (t.deps || []).join(", ") || "—"],
            ["decided", t.decided_by || "—"],
          ]),
          lease ? h("div", { class: "lease-box", dataset: { active: String(active) } },
            h("div", { class: "label" }, active ? "Live lease" : "Expired lease"),
            h("div", { class: "lease-line" },
              h("b", { text: lease.agent || "—" }),
              h("span", { class: "mono faint" }, `since ${fmtDate(lease.since, { time: true })}`),
              h("span", { class: "mono faint" }, `${active ? "expires" : "expired"} ${fmtDate(lease.expires, { time: true })}`)),
            lease.checkpoint ? h("div", { class: "lease-note", text: lease.checkpoint }) : null) : null,
          t.desc ? h("div", { class: "section-flat" },
            sectionTitle("Brief"),
            h("div", { class: "task-desc", text: t.desc })) : null,
          Object.keys(t.votes || {}).length ? h("div", { class: "section-flat" },
            sectionTitle("Ballots", h("span", { class: "label" }, `${Object.keys(t.votes).length} · quorum 2`)),
            h("div", { class: "ballots" }, ...Object.entries(t.votes).map(([who, v]) =>
              h("div", { class: "ballot", dataset: { v: v.vote } },
                h("div", { class: "ballot-head" },
                  h("span", { class: "chip " + (v.vote === "accept" ? "st-done" : "st-blocked") }, v.vote.toUpperCase()),
                  h("b", { text: who }),
                  v.inspected ? h("span", { class: "tag", text: "INSPECTED" }) : h("span", { class: "tag", style: { color: "var(--red)" } }, "NOT INSPECTED"),
                  h("span", { class: "mono faint", style: { marginLeft: "auto", fontSize: "9.5px" } }, (v.ts || "").slice(0, 16))),
                h("div", { class: "ballot-text", text: v.reason || "" }))))) : null,
          (t.history || []).length ? h("div", { class: "section-flat" },
            sectionTitle("History", h("span", { class: "label" }, `${t.history.length}`)),
            h("div", { class: "history" }, ...t.history.slice().reverse().map((hh) =>
              h("div", { class: "history-row" },
                h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, (hh.ts || "").replace("T", " ").slice(0, 16)),
                h("b", { text: hh.by || "—" }),
                h("span", { class: "dim", text: hh.action || "" }))))) : null,
          h("div", { class: "drawer-foot" }, codeBlock(`python3 bin/chatcode tasks show ${t.id}`)),
        ),
      );
      return frag;
    }

    function renderJob(j) {
      const phases = j.phases || [];
      return h("div", {},
        drawerHead(j.id, j.title, statusChip(j.status)),
        h("div", { class: "drawer-body" },
          kvList([
            ["owner", j.owner || "unclaimed"],
            ["phase", j.phase || "—"],
            ["updated", fmtDate(j.updated_ts, { time: true })],
            ["claims", j.claims.map((c) => `${c.agent} @ ${(c.ts || "").slice(0, 16)}`).join(" · ") || "—"],
            ["path", h("span", { class: "mono", text: j.path })],
          ]),
          phases.length ? h("div", { class: "section-flat" },
            sectionTitle("Phases"),
            h("div", { class: "phase-table" },
              h("div", { class: "phase-row phase-head" },
                h("span", {}, "phase"), h("span", {}, "deliverable"), h("span", {}, "evidence"), h("span", {}, "min")),
              ...phases.map((p) => h("div", { class: "phase-row" },
                h("b", { text: p.phase }), h("span", { class: "truncate", text: p.deliverable }),
                h("span", { class: "dim truncate", text: p.evidence }), h("span", { class: "mono", text: p.min_hours }))))) : null,
          h("div", { class: "section-flat" },
            sectionTitle("Phase log", h("span", { class: "label" }, `${j.phase_log.length}`)),
            h("div", { class: "history" }, ...j.phase_log.slice().reverse().map((p) =>
              h("div", { class: "history-row" },
                h("span", { class: "mono faint", style: { fontSize: "9.5px" } }, (p.ts || "").replace("T", " ").slice(0, 16)),
                h("span", { class: "tag", text: `${p.phase || ""} ${p.action || ""}` }),
                h("span", { class: "dim truncate", text: p.note || "" }))))),
          h("div", { class: "section-flat" },
            sectionTitle("Evidence", h("span", { class: "label" }, `${j.evidence.length} files`)),
            h("div", { class: "evidence" }, ...j.evidence.map((e) => h("span", { class: "tag", text: e })))),
          j.brief ? h("details", { class: "section-flat" }, h("summary", { class: "label" }, "Brief"), h("div", { class: "md-wrap" }, markdown(j.brief))) : null,
          j.handoff ? h("details", { class: "section-flat" }, h("summary", { class: "label" }, "Handoff"), h("div", { class: "md-wrap" }, markdown(j.handoff))) : null,
        ));
    }

    async function copyCmd(cmd) {
      const { copyText } = await import("../util.js");
      const ok = await copyText(cmd);
      toast(ok ? "Command copied" : "Copy failed", cmd, ok ? "ok" : "error", 2600);
    }

    async function runAction(name, params) {
      try {
        const res = await action(name, params);
        toast("Board updated", (res.output || "").split("\n").slice(-2).join(" "), "ok", 6000);
        setTimeout(refreshList, 1200);
      } catch (err) {
        toast("Action refused", err.message, "error", 7000);
      }
    }

    (async () => {
      try {
        const cfg = await api.config();
        writeMode = cfg.actions_enabled;
        const mode = document.getElementById("board-mode");
        if (mode) mode.textContent = writeMode ? `WRITE · ${cfg.agent_name}` : "READ-ONLY";
      } catch { /* ignore */ }
      renderStatusSeg();
      renderHead();
      refreshList();
    })();
    document.addEventListener("agency:change", () => { if (body.isConnected) { refreshList(); } }, { signal });
    document.addEventListener("agency:open-task", (e) => { if (e.detail) showTask(e.detail); }, { signal });
  },
};
