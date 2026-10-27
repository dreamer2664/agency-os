// util.js — DOM, formatting and a small virtual list. No dependencies.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

export function fmtNum(n) {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(n);
}

export function fmtAge(min) {
  if (min === null || min === undefined) return "never";
  if (min < 0) return "now";
  if (min < 1) return "now";
  if (min < 60) return `${Math.round(min)}m`;
  if (min < 1440) return `${Math.floor(min / 60)}h ${String(Math.round(min % 60)).padStart(2, "0")}m`;
  return `${Math.floor(min / 1440)}d ${String(Math.floor((min % 1440) / 60)).padStart(2, "0")}h`;
}

export function parseTs(ts) {
  if (!ts) return null;
  const d = new Date(/Z$|[+-]\d\d:?\d\d$/.test(ts) ? ts : ts + "Z");
  return isNaN(d.getTime()) ? null : d;
}

export function fmtClock(d, withSeconds = true) {
  if (!d) return "—";
  const p = (n) => String(n).padStart(2, "0");
  return withSeconds
    ? `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
    : `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

export function fmtDate(ts, opts = {}) {
  const d = typeof ts === "string" ? parseTs(ts) : ts;
  if (!d) return "—";
  const p = (n) => String(n).padStart(2, "0");
  const date = `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
  return opts.time ? `${date} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}Z` : date;
}

export function ago(ts) {
  const d = typeof ts === "string" ? parseTs(ts) : ts;
  if (!d) return "never";
  return fmtAge((Date.now() - d.getTime()) / 60000);
}

export function debounce(fn, ms = 220) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export function debounceRaf(fn) {
  let raf = null;
  return (...args) => {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = null; fn(...args); });
  };
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

export function codeBlock(text, label = "") {
  return h("div", { class: "code" },
    h("code", { text }),
    h("button", {
      class: "copy", title: "Copy to clipboard",
      onclick: async (e) => {
        const ok = await copyText(text);
        e.currentTarget.style.color = ok ? "var(--green)" : "var(--red)";
        setTimeout(() => { e.currentTarget.style.color = ""; }, 900);
      },
    }, icon("copy")),
    label ? h("span", { class: "faint", style: { fontSize: "9px", letterSpacing: ".1em" } }, label) : null,
  );
}

export const STATUS_LABEL = {
  open: "OPEN", claimed: "CLAIMED", review: "REVIEW", blocked: "BLOCKED",
  done: "DONE", dropped: "DROPPED",
  working: "PRODUCTIVE", idle: "IDLE — NO ASSIGNMENT", unknown: "UNKNOWN",
  stalled: "STALLED", retired: "RETIRED", degraded: "DEGRADED",
};

export function chip(kind, text) {
  return h("span", { class: `chip st-${kind}` }, text || STATUS_LABEL[kind] || kind);
}

export function badge(text, kind = "") {
  return h("span", { class: `tag ${kind}` }, text);
}

/* ------------------------------------------------------------------ icons */
const PATHS = {
  overview: "M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z",
  agents: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  board: "M4 4h16v4H4zM4 10h10v4H4zM4 16h16v4H4z",
  comms: "M21 12a8 8 0 0 1-8 8H6l-3 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z",
  review: "M4 4h11l5 5v11H4zM9 12l2 2 4-4",
  repos: "M6 3h12v18H6zM9 7h6M9 11h6M9 15h4",
  records: "M4 4h16v16H4zM8 8h8M8 12h8M8 16h5",
  resources: "M3 12h4l2-6 4 12 2-6h6",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 14.9H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 9 2.6V2a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.6 1h.1a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  close: "M6 6l12 12M18 6L6 18",
  min: "M5 12h14",
  max: "M5 5h14v14H5z",
  restore: "M8 8V5h11v11h-3M5 8h11v11H5z",
  copy: "M9 9h10v10H9zM5 15V5h10",
  external: "M14 4h6v6M20 4l-8 8M18 14v6H4V6h6",
  sync: "M21 12a9 9 0 1 1-3-6.7M21 3v6h-6",
  alert: "M12 3l9 17H3zM12 9v5M12 17h.01",
  check: "M4 12l5 5L20 6",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  bolt: "M13 2L4 14h6l-1 8 9-12h-6z",
  lock: "M6 10V8a6 6 0 1 1 12 0v2M5 10h14v11H5z",
  dot: "M12 12h.01",
};

export function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", name === "dot" ? "6" : "1.6");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", PATHS[name] || PATHS.dot);
  svg.appendChild(p);
  return svg;
}

export function brandMark(size = 26) {
  const wrap = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  wrap.setAttribute("viewBox", "0 0 32 32");
  wrap.setAttribute("width", size);
  wrap.setAttribute("height", size);
  wrap.setAttribute("fill", "none");
  wrap.setAttribute("stroke", "currentColor");
  wrap.setAttribute("stroke-width", "1.5");
  wrap.innerHTML = `
    <path d="M16 2.5 29 9.5v13L16 29.5 3 22.5v-13z" opacity=".55"/>
    <path d="M16 8.2 24 12.6v8.8L16 25.8 8 21.4v-8.8z"/>
    <circle cx="16" cy="17" r="3.1" fill="currentColor" stroke="none"/>
    <path d="M16 3v5.2M16 23.8V29M3.6 9.9 8 12.3M24 21.7l4.4 2.4" opacity=".5"/>`;
  return wrap;
}

/* ------------------------------------------------------------- virtual list */
export class VirtualList {
  /** Fixed-height row virtualisation: 10k rows cost ~30 DOM nodes. */
  constructor({ rowHeight = 30, overscan = 6, className = "", row = null, empty = null }) {
    this.rowHeight = rowHeight;
    this.overscan = overscan;
    this.row = row;
    this.emptyHtml = empty;
    this.el = h("div", { class: `vlist ${className}` });
    this.inner = h("div", { class: "vlist-inner" });
    this.el.appendChild(this.inner);
    this.rows = [];
    this.el.addEventListener("scroll", debounceRaf(() => this.render()), { passive: true });
    this._onResize = debounceRaf(() => this.render());
    window.addEventListener("resize", this._onResize);
  }
  setRows(rows) {
    this.rows = rows || [];
    this.inner.style.height = `${this.rows.length * this.rowHeight}px`;
    this.el.scrollTop = Math.min(this.el.scrollTop, Math.max(0, this.rows.length * this.rowHeight - this.el.clientHeight));
    this.render();
    return this;
  }
  render() {
    if (!this.rows.length) {
      this.inner.innerHTML = "";
      if (this.emptyHtml) {
        this.inner.appendChild(typeof this.emptyHtml === "string"
          ? h("div", { class: "vlist-empty", html: this.emptyHtml })
          : this.emptyHtml);
      }
      return;
    }
    const vh = this.el.clientHeight || 420;
    const first = Math.max(0, Math.floor(this.el.scrollTop / this.rowHeight) - this.overscan);
    const count = Math.ceil(vh / this.rowHeight) + this.overscan * 2;
    const last = Math.min(this.rows.length, first + count);
    const frag = document.createDocumentFragment();
    for (let i = first; i < last; i++) {
      const node = this.row(this.rows[i], i);
      node.classList.add("vrow");
      node.style.top = `${i * this.rowHeight}px`;
      node.style.height = `${this.rowHeight}px`;
      frag.appendChild(node);
    }
    this.inner.replaceChildren(frag);
  }
  destroy() {
    window.removeEventListener("resize", this._onResize);
    this.el.remove();
  }
}

export function toast(title, body = "", kind = "", ms = 4200) {
  let host = $("#toasts");
  if (!host) {
    host = h("div", { class: "toasts", id: "toasts" });
    document.body.appendChild(host);
  }
  const el = h("div", { class: "toast", dataset: { kind } },
    h("b", { text: title }),
    body ? h("div", { class: "mono", text: body }) : null);
  host.appendChild(el);
  while (host.children.length > 4) host.firstChild.remove();
  setTimeout(() => {
    el.style.transition = "opacity .2s, transform .2s";
    el.style.opacity = "0";
    el.style.transform = "translateX(8px)";
    setTimeout(() => el.remove(), 220);
  }, ms);
  return el;
}
