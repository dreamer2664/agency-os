// shared view helpers: the agency's own language for cards, chips and states.
import { h, icon, chip, fmtAge, fmtDate, ago, VirtualList, codeBlock, STATUS_LABEL } from "../util.js";

export const bus = new EventTarget();
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));

export function openTask(id) { emit("open:task", id); }
export function openAgent(name) { emit("open:agent", name); }
export function navigate(id) { emit("navigate", id); }

export function paneHead(...children) {
  return h("div", { class: "pane-head" }, ...children);
}

export function sectionTitle(text, extra = null) {
  return h("h3", { class: "section-title" }, text, extra);
}

export function emptyState(title, body, action = null) {
  return h("div", { class: "empty" },
    h("div", { class: "mark" }, icon("eye", 22)),
    h("b", { text: title }),
    h("div", { text: body }),
    action);
}

export function statusChip(status) {
  return chip(status, STATUS_LABEL[status] || status);
}

export function agentChip(state) {
  const map = { working: "PRODUCTIVE", idle: "IDLE", blocked: "BLOCKED", stalled: "STALLED", retired: "RETIRED", unknown: "UNKNOWN" };
  return h("span", { class: `chip st-${state}` }, map[state] || state);
}

export function taskRow(task, onOpen = openTask) {
  return h("div", { class: "grid-row", role: "row", tabindex: "0",
    onclick: () => onOpen(task.id),
    onkeydown: (e) => { if (e.key === "Enter") onOpen(task.id); } },
    h("div", { class: "cell" }, statusChip(task.status)),
    h("div", { class: "cell mono", style: { fontSize: "10.5px", color: "var(--ink-4)" } }, task.id),
    h("div", { class: "cell truncate", title: task.title }, task.title || "(untitled)"),
    h("div", { class: "cell", style: { color: "var(--ink-3)" } }, task.owner || "—"),
    h("div", { class: "cell num", style: { color: task.priority === 1 ? "var(--signal)" : "var(--ink-3)" } }, task.priority ?? "—"),
    h("div", { class: "cell num", style: { color: "var(--ink-4)" } }, fmtAge(task.age_min)),
    h("div", { class: "cell num" }, task.votes || "—"),
    h("div", { class: "cell num", style: { color: "var(--ink-4)" } }, fmtAge(task.updated_age_min)),
  );
}

export const TASK_COLUMNS = [
  { label: "status", width: "92px" },
  { label: "id", width: "104px" },
  { label: "card", width: "minmax(0, 1fr)" },
  { label: "owner", width: "94px" },
  { label: "pri", width: "34px", num: true },
  { label: "age", width: "62px", num: true },
  { label: "votes", width: "46px", num: true },
  { label: "touched", width: "68px", num: true },
];

export function applyGrid(node, columns) {
  node.style.display = "grid";
  node.style.gridTemplateColumns = columns.map((c) => c.width).join(" ");
  node.style.alignItems = "center";
  return node;
}

export function gridHead(columns) {
  return h("div", {
    class: "grid-head",
    style: { gridTemplateColumns: columns.map((c) => c.width).join(" ") },
    role: "row",
  }, ...columns.map((c) => h("div", { class: `cell ${c.num ? "num" : ""}`, text: c.label })));
}

export function gridBody(columns, rows, rowFn, { rowHeight = 30, empty = "" } = {}) {
  const v = new VirtualList({
    rowHeight,
    className: "grid-body",
    row: (r, i) => {
      const node = rowFn(r, i);
      node.style.gridTemplateColumns = columns.map((c) => c.width).join(" ");
      node.style.display = "grid";
      node.style.alignItems = "center";
      node.style.gap = "0";
      node.classList.add("grid-row");
      return node;
    },
    empty,
  });
  v.setRows(rows);
  return v;
}

export function countPill(n, kind = "") {
  return h("span", { class: `count ${kind}` }, String(n));
}

export function linkOut(href, label) {
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", class: "ext" },
    label || href.replace(/^https?:\/\//, ""), icon("external", 10));
}

export function kvList(pairs) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of pairs) {
    if (v === null || v === undefined || v === "") continue;
    dl.append(h("dt", { text: k }), h("dd", {}, v instanceof Node ? v : String(v)));
  }
  return dl;
}

export function markdown(md) {
  // Deliberately small: headings, bullets, bold, inline code, links, rules.
  const out = h("div", { class: "md" });
  const lines = String(md || "").split("\n");
  let list = null;
  for (const raw of lines) {
    const line = raw.replace(/\r$/, "");
    if (/^###?\s+/.test(line)) { list = null; out.appendChild(h("h4", { text: line.replace(/^###?\s+/, "") })); continue; }
    if (/^##\s+/.test(line)) { list = null; out.appendChild(h("h3", { text: line.replace(/^##\s+/, "") })); continue; }
    if (/^#\s+/.test(line)) { list = null; out.appendChild(h("h2", { text: line.replace(/^#\s+/, "") })); continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      if (!list) { list = h("ul"); out.appendChild(list); }
      list.appendChild(h("li", { html: inline(line.replace(/^\s*[-*]\s+/, "")) }));
      continue;
    }
    if (!line.trim()) { list = null; out.appendChild(h("div", { class: "md-gap" })); continue; }
    list = null;
    out.appendChild(h("p", { html: inline(line) }));
  }
  return out;
}

function inline(s) {
  const esc = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

export function timeCell(ts, opts = {}) {
  const d = ts ? new Date(ts) : null;
  if (!d || isNaN(d.getTime())) return h("span", { class: "faint" }, "—");
  return h("span", { class: "mono", title: fmtDate(ts, { time: true }) }, ago(ts));
}

export function commandHint(command, note = "") {
  return h("div", { style: { display: "grid", gap: "4px" } },
    codeBlock(command),
    note ? h("div", { class: "faint", style: { fontSize: "10px" }, text: note }) : null);
}

export { h, icon, chip, fmtAge, fmtDate, ago, codeBlock, VirtualList };
