// wm.js — a small window manager: drag, resize, snap, persist. ~200 lines.
import { h, icon, clamp, debounce } from "./util.js";

const STORE_KEY = "agencyos.wm.v1";

export class WindowManager {
  constructor(deskEl, { onChange } = {}) {
    this.desk = deskEl;
    this.wins = new Map();    // id -> {el, view, state}
    this.z = 10;
    this.onChange = onChange || (() => {});
    this.layout = this._load();
    this.focused = null;
    this._bindGlobal();
  }

  _load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
    catch { return {}; }
  }

  _save = debounce(() => {
    const out = {};
    for (const [id, w] of this.wins) out[id] = w.state;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(out)); } catch { /* quota */ }
  }, 350);

  resetLayout() {
    try { localStorage.removeItem(STORE_KEY); } catch { /* ignore */ }
    this.layout = {};
    for (const [id, w] of this.wins) {
      const s = this._defaultState(id, w.view);
      Object.assign(w.state, s);
      this._apply(id);
    }
    this.onChange();
  }

  _defaultState(id, view) {
    const dw = this.desk.clientWidth;
    const dh = this.desk.clientHeight;
    const want = view.size || [960, 620];
    const w = Math.min(want[0], Math.max(320, dw - 48));
    const hgt = Math.min(want[1], Math.max(240, dh - 48));
    const idx = this.wins.size;
    return {
      x: Math.max(12, Math.round((dw - w) / 2) + (idx % 4) * 18 - 27),
      y: Math.max(10, Math.round((dh - hgt) / 2) + (idx % 4) * 16 - 24),
      w, h: hgt, max: dw < 760, min: false,
    };
  }

  open(id, view) {
    let win = this.wins.get(id);
    if (win) {
      win.state.min = false;
      this.focus(id);
      return win;
    }
    const el = h("section", { class: "win", dataset: { view: id }, role: "dialog", "aria-label": view.title });
    const body = h("div", { class: "win-body" });
    const sub = h("span", { class: "win-sub" });
    const bar = h("header", { class: "win-bar" },
      h("span", { class: "win-icon" }, icon(view.icon || "dot", 14)),
      h("span", { class: "win-title", text: view.title }),
      sub,
      h("div", { class: "win-controls" },
        h("button", { class: "win-btn", title: "Minimise", onclick: (e) => { e.stopPropagation(); this.minimize(id); } }, icon("min", 12)),
        h("button", { class: "win-btn", title: "Maximise", onclick: (e) => { e.stopPropagation(); this.toggleMax(id); } }, icon("max", 11)),
        h("button", { class: "win-btn close", title: "Close", onclick: (e) => { e.stopPropagation(); this.close(id); } }, icon("close", 11)),
      ),
    );
    const grip = h("div", { class: "win-grip" });
    el.append(bar, body, grip);
    this.desk.appendChild(el);
    const state = this.layout[id] ? { ...this._defaultState(id, view), ...this.layout[id] } : this._defaultState(id, view);
    win = { id, el, body, sub, view, state, mounted: false, ctrl: new AbortController(), cleanup: [] };
    this.wins.set(id, win);
    this._wireDrag(win, bar);
    this._wireResize(win, grip);
    bar.addEventListener("dblclick", () => this.toggleMax(id));
    this._apply(id);
    this.focus(id);
    view.mount(body, {
      win, signal: win.ctrl.signal,
      sub: (t) => { sub.textContent = t || ""; },
      onClose: (fn) => win.cleanup.push(fn),
    });
    win.mounted = true;
    this.onChange();
    return win;
  }

  _wireDrag(win, bar) {
    let start = null;
    bar.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".win-btn")) return;
      start = { x: e.clientX, y: e.clientY, ...win.state };
      bar.setPointerCapture(e.pointerId);
      win.el.style.transition = "none";
    });
    bar.addEventListener("pointermove", (e) => {
      if (!start || win.state.max) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      win.state.x = clamp(start.x + dx, -win.state.w + 120, this.desk.clientWidth - 120);
      win.state.y = clamp(start.y + dy, 0, this.desk.clientHeight - 44);
      this._place(win);
    });
    const end = () => {
      if (!start) return;
      start = null;
      win.el.style.transition = "";
      this._save();
    };
    bar.addEventListener("pointerup", end);
    bar.addEventListener("pointercancel", end);
  }

  _wireResize(win, grip) {
    let start = null;
    grip.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      start = { x: e.clientX, y: e.clientY, w: win.state.w, h: win.state.h };
      grip.setPointerCapture(e.pointerId);
    });
    grip.addEventListener("pointermove", (e) => {
      if (!start) return;
      win.state.w = Math.max(360, start.w + e.clientX - start.x);
      win.state.h = Math.max(220, start.h + e.clientY - start.y);
      this._place(win);
    });
    const end = () => { if (start) { start = null; this._save(); } };
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
  }

  _place(win) {
    const { x, y, w, h } = win.state;
    if (win.state.max) {
      win.el.classList.add("max");
      Object.assign(win.el.style, { left: "0px", top: "0px", width: "100%", height: "100%" });
    } else {
      win.el.classList.remove("max");
      Object.assign(win.el.style, {
        left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px`,
      });
    }
    win.el.dataset.min = win.state.min ? "true" : "false";
  }

  _apply(id) {
    const win = this.wins.get(id);
    if (!win) return;
    this._place(win);
    this.layout[id] = win.state;
    this._save();
  }

  focus(id) {
    const win = this.wins.get(id);
    if (!win) return;
    this.focused = id;
    win.state.min = false;
    this._place(win);
    win.el.style.zIndex = String(++this.z);
    for (const [wid, w] of this.wins) w.el.dataset.focused = wid === id ? "true" : "false";
    this.onChange();
  }

  close(id) {
    const win = this.wins.get(id);
    if (!win) return;
    win.ctrl.abort();
    for (const fn of win.cleanup) { try { fn(); } catch { /* ignore */ } }
    win.el.style.transition = "opacity .12s, transform .12s";
    win.el.style.opacity = "0";
    win.el.style.transform = "scale(.995)";
    setTimeout(() => {
      win.el.remove();
      this.wins.delete(id);
      if (this.focused === id) this.focused = null;
      this.onChange();
    }, 110);
  }

  minimize(id) {
    const win = this.wins.get(id);
    if (!win) return;
    win.state.min = true;
    win.el.dataset.min = "true";
    if (this.focused === id) this.focused = null;
    this._save();
    this.onChange();
  }

  toggleMax(id) {
    const win = this.wins.get(id);
    if (!win) return;
    win.state.max = !win.state.max;
    this._apply(id);
    this.focus(id);
  }

  restore(id) {
    const win = this.wins.get(id);
    if (!win) return;
    if (win.state.min || this.focused !== id) this.focus(id);
    else this.minimize(id);
    this.onChange();
  }

  isOpen(id) { return this.wins.has(id); }

  _bindGlobal() {
    window.addEventListener("resize", debounce(() => {
      for (const [, w] of this.wins) {
        if (!w.state.max) {
          w.state.x = clamp(w.state.x, -w.state.w + 120, Math.max(0, this.desk.clientWidth - 120));
          w.state.y = clamp(w.state.y, 0, Math.max(0, this.desk.clientHeight - 44));
        }
      }
      this._save();
    }, 160));
    document.addEventListener("keydown", (e) => {
      if (!e.altKey) return;
      if (e.key === "w" && this.focused) { e.preventDefault(); this.close(this.focused); }
      if (e.key === "m" && this.focused) { e.preventDefault(); this.minimize(this.focused); }
      if (e.key === "Enter" && this.focused) { e.preventDefault(); this.toggleMax(this.focused); }
    });
  }
}
