// api.js — the only way the deck talks to agencyd.

const JSON_CACHE = new Map();

export async function get(path, { ttl = 0, force = false } = {}) {
  const now = Date.now();
  const hit = JSON_CACHE.get(path);
  if (!force && ttl > 0 && hit && now - hit.t < ttl * 1000) return hit.data;
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const j = await res.json();
      msg = j.error || msg;
      if (j.detail) msg += ` — ${j.detail}`;
    } catch { /* non-JSON error body */ }
    throw new Error(msg);
  }
  const data = await res.json();
  JSON_CACHE.set(path, { t: now, data });
  return data;
}

export function invalidate(prefix = "") {
  for (const k of Array.from(JSON_CACHE.keys())) {
    if (k.startsWith(prefix)) JSON_CACHE.delete(k);
  }
}

export async function action(name, params = {}) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AgencyOS": "1" },
    body: JSON.stringify({ action: name, params }),
  });
  const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `action failed (${res.status})`);
  }
  invalidate();
  return data;
}

export const api = {
  summary: () => get("/api/summary", { ttl: 2 }),
  agents: () => get("/api/agents", { ttl: 2 }),
  agent: (n) => get(`/api/agents/${encodeURIComponent(n)}`, { ttl: 4 }),
  tasks: (q = {}) => get(`/api/tasks?${new URLSearchParams(q)}`, { ttl: 2 }),
  task: (id) => get(`/api/tasks/${encodeURIComponent(id)}`, { ttl: 4 }),
  jobs: () => get("/api/jobs", { ttl: 4 }),
  job: (id) => get(`/api/jobs/${encodeURIComponent(id)}`, { ttl: 4 }),
  review: () => get("/api/review", { ttl: 2 }),
  channels: () => get("/api/channels", { ttl: 4 }),
  messages: (q) => get(`/api/messages?${new URLSearchParams(q)}`, { ttl: 2 }),
  wire: (q = {}) => get(`/api/wire?${new URLSearchParams(q)}`, { ttl: 4 }),
  records: (q = {}) => get(`/api/records?${new URLSearchParams(q)}`, { ttl: 4 }),
  activity: (q = {}) => get(`/api/activity?${new URLSearchParams(q)}`, { ttl: 4 }),
  sources: () => get("/api/sources", { ttl: 3 }),
  resources: () => get("/api/resources", { ttl: 2 }),
  github: (refresh = false) => get(`/api/github/overview${refresh ? "?refresh=1" : ""}`, { ttl: 60 }),
  config: () => get("/api/config", { ttl: 10 }),
  search: (q) => get(`/api/search?q=${encodeURIComponent(q)}`, { ttl: 8 }),
  ping: () => get("/api/ping", { ttl: 0 }),
};

/** SSE subscription. Returns a disposer. */
export function subscribe(onChange, onStatus) {
  let es;
  let retry = 1000;
  let closed = false;
  const connect = () => {
    if (closed) return;
    es = new EventSource("/api/events");
    es.addEventListener("open", () => {
      retry = 1000;
      onStatus && onStatus("live");
    });
    es.addEventListener("hello", () => onStatus && onStatus("live"));
    es.addEventListener("change", (ev) => {
      try { onChange(JSON.parse(ev.data)); } catch { onChange({}); }
    });
    es.addEventListener("error", () => {
      onStatus && onStatus("down");
      es.close();
      if (closed) return;
      retry = Math.min(retry * 1.7, 15000);
      setTimeout(connect, retry);
    });
  };
  connect();
  return () => { closed = true; es && es.close(); };
}
