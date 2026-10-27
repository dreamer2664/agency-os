// records.js — the durable record: push ledger, shift notes, the formalcode wire.
import { api } from "../api.js";
import { h, icon, fmtDate, ago, VirtualList } from "../util.js";
import { emptyState, markdown, sectionTitle, linkOut, openTask } from "./common.js";

function shortStamp(v) {
  const s = String(v || "");
  const d = s.slice(5, 10);
  const t = s.includes("T") ? s.slice(11, 16) : "";
  return `${d} ${t}`.trim();
}

export const records = {
  id: "records",
  title: "Records",
  icon: "records",
  size: [1000, 640],
  mount(body, { signal, sub }) {
    let tab = "pushes";
    let wireRepo = "";
    let wireQ = "";
    let shifts = [];
    let selectedShift = null;

    const tabs = h("div", { class: "seg" },
      tabBtn("pushes", "Push ledger"), tabBtn("shifts", "Shift notes"), tabBtn("wire", "Formalcode wire"));
    const tools = h("div", { class: "filters" });
    const head = h("div", { class: "pane-head" }, tabs, h("span", { style: { flex: 1 } }), tools);
    const stage = h("div", { class: "records-stage" });
    body.append(head, stage);

    function tabBtn(k, label) {
      return h("button", { dataset: { k }, "aria-pressed": String(tab === k), onclick: () => {
        tab = k;
        for (const b of tabs.children) b.setAttribute("aria-pressed", String(b.dataset.k === k));
        render();
      } }, label);
    }

    async function render() {
      if (!body.isConnected) return;
      tools.replaceChildren();
      if (tab === "pushes") return renderPushes();
      if (tab === "shifts") return renderShifts();
      return renderWire();
    }

    async function renderPushes() {
      const { rows } = await api.records({ kind: "pushes", limit: 500 });
      sub(`${rows.length} ledger rows`);
      tools.append(
        h("span", { class: "label" }, "every push, every repo"),
        linkOut("https://github.com/dreamer2664/storagecode/blob/main/PUSHES.md", "PUSHES.md"),
      );
      const v = new VirtualList({
        rowHeight: 48,
        className: "grid-body",
        row: (p) => h("div", { class: "push-row" },
          h("div", { class: "mono faint", style: { fontSize: "10px", textAlign: "right" } }, shortStamp(p.date)),
          h("div", {}, h("b", { text: p.agent })),
          h("div", {}, h("span", { class: "tag", text: (p.repo || "").replace("dreamer2664/", "") })),
          h("div", {},
            h("div", { class: "truncate", text: p.what, title: p.what }),
            h("div", { class: "faint truncate", style: { fontSize: "10px" }, title: p.next }, `next: ${p.next}`)),
          h("div", { style: { textAlign: "right" } },
            p.sha ? h("a", { class: "mono", style: { fontSize: "10px" }, href: `https://github.com/dreamer2664/${p.repo}/commit/${p.sha}`, target: "_blank", rel: "noopener" }, p.sha)
              : h("span", { class: "faint", text: "—" }),
            p.pr ? h("div", { class: "mono faint", style: { fontSize: "9.5px" } }, `PR #${p.pr}`) : null)),
        empty: "No ledger rows found in storagecode/PUSHES.md.",
      });
      v.setRows(rows);
      stage.replaceChildren(v.el);
      v.el.style.height = "100%";
    }

    async function renderShifts() {
      const data = await api.records({ kind: "shifts", limit: 200 });
      shifts = data.rows;
      sub(`${shifts.length} shift notes`);
      tools.append(linkOut("https://github.com/dreamer2664/storagecode/tree/main/shifts", "shifts/"));
      const list = new VirtualList({
        rowHeight: 52, className: "shift-list",
        row: (s) => h("div", { class: "shift-row", dataset: { active: String(s.file === selectedShift?.file) },
          onclick: () => { selectedShift = s; renderShifts(); } },
          h("div", { class: "mono faint", style: { fontSize: "10px", width: "76px" } }, s.date),
          h("div", { style: { minWidth: 0, flex: 1 } },
            h("div", { class: "truncate", style: { fontWeight: 600 }, text: s.agent }),
            h("div", { class: "faint truncate", style: { fontSize: "10.5px" }, text: s.excerpt })),
        ),
        empty: "No shift notes.",
      });
      list.setRows(shifts);
      if (!selectedShift && shifts.length) selectedShift = shifts[0];
      const detail = h("div", { class: "pane-scroll shift-detail" },
        selectedShift
          ? h("div", { class: "section" },
            h("div", { class: "label" }, `${selectedShift.date} · ${selectedShift.agent}`),
            h("h2", { class: "shift-title", text: selectedShift.title }),
            h("div", { class: "md-wrap" }, markdown(selectedShift.body)),
            h("div", { style: { marginTop: "10px" } }, linkOut(selectedShift.url, "source on GitHub")))
          : emptyState("No shift note selected", "Shift notes are how a dead operative's shift survives them."));
      stage.replaceChildren(h("div", { class: "split" },
        h("div", { class: "col", style: { background: "var(--bg-2)" } }, list.el),
        h("div", { class: "col" }, detail)));
      list.el.style.height = "100%";
    }

    async function renderWire() {
      const repos = ["", "chatcode", "agency", "storagecode", "superocr", "storage", "sable", "pc-eye"];
      tools.append(
        h("select", { class: "input", onchange: (e) => { wireRepo = e.target.value; renderWire(); } },
          ...repos.map((r) => h("option", { value: r, selected: r === wireRepo }, r || "all repos"))),
        h("input", { class: "input", placeholder: "search the wire…", style: { width: "180px" },
          value: wireQ, oninput: (e) => { wireQ = e.target.value; clearTimeout(window.__wireT); window.__wireT = setTimeout(renderWire, 260); } }),
        linkOut("https://ntfy.sh/formalcode", "live topic"));
      const { events } = await api.wire({ limit: 400, repo: wireRepo || undefined, q: wireQ || undefined });
      sub(`${events.length} wire events`);
      const v = new VirtualList({
        rowHeight: 42,
        row: (e) => h("div", { class: "wire-row" },
          h("div", { class: "mono faint", style: { fontSize: "10px" } }, e.ts.slice(5, 16).replace("T", " ")),
          h("div", {}, h("span", { class: "tag", text: e.repo || "—" })),
          h("div", {}, h("b", { text: e.author || "—" })),
          h("div", {}, h("div", { class: "truncate", text: e.text, title: e.text })),
          e.url ? h("a", { href: e.url, target: "_blank", rel: "noopener", class: "mono", style: { fontSize: "10px" } }, icon("external", 11)) : null),
        empty: "The wire archive is empty for this filter.",
      });
      v.setRows(events);
      stage.replaceChildren(v.el);
      v.el.style.height = "100%";
    }

    render();
    document.addEventListener("agency:change", () => { if (body.isConnected) render(); }, { signal });
  },
};
