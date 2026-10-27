"""The Agency OS daemon: one stdlib HTTP server, no framework, no build step.

Serves the deck (static files from ui/) and a small JSON API over the local
repository mirrors.  Server-Sent Events push a single `version` bump whenever the
filesystem signature changes; the browser then re-fetches only the panel it is
looking at.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import os
import re
import socket
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import resources
from .actions import ActionError, Actions
from .collect import Collector, human_age, iso, now, parse_ts
from .config import VERSION
from .github import GitHub
from .store import State

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
CORE_REPOS = ["dreamer2664/agency", "dreamer2664/chatcode", "dreamer2664/storagecode"]


class Logger:
    def __init__(self, path: Path, max_bytes: int = 2 * 1024 * 1024):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def __call__(self, msg: str):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n"
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    os.replace(self.path, self.path.with_suffix(".1"))
            except OSError:
                pass
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass


class App:
    """Everything the request handlers need, built once."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.log = Logger(Path(cfg.home) / "log" / "agencyd.log", cfg.log_max_bytes)
        self.state = State(cfg, logger=self.log)
        self.actions = Actions(cfg, self.state.sources, logger=self.log)
        self.github = GitHub("dreamer2664", Path(cfg.data_dir) / "cache" / "github",
                             token=cfg.token(), ttl=cfg.gh_cache_ttl, logger=self.log)
        self.state.github = self.github
        self.started = time.time()


def _json_default(o):
    return str(o)


class Handler(BaseHTTPRequestHandler):
    server_version = f"AgencyOS/{VERSION}"
    protocol_version = "HTTP/1.1"
    app: App = None  # assigned below

    # --------------------------------------------------------------- helpers
    def log_message(self, fmt, *args):
        if "/api/events" in self.path:
            return
        self.app.log(f'{self.client_address[0]} {fmt % args}')

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None,
              etag: str | None = None) -> None:
        if self._if_none_match(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        accept = self.headers.get("Accept-Encoding", "")
        if len(body) > 1024 and "gzip" in accept and ctype.startswith(("application/json", "text/", "image/svg")):
            body = gzip.compress(body, 6)
            gz = True
        else:
            gz = False
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if etag:
            self.send_header("ETag", etag)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _if_none_match(self, etag: str | None) -> bool:
        if not etag:
            return False
        hdr = self.headers.get("If-None-Match", "")
        return etag in [h.strip() for h in hdr.split(",")]

    def json(self, obj, status: int = 200, etag: bool = False):
        body = json.dumps(obj, default=_json_default, separators=(",", ":")).encode("utf-8")
        tag = None
        if etag:
            tag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
        self._send(status, body, "application/json; charset=utf-8", etag=tag)

    def error(self, status: int, message: str, detail: str = ""):
        self.json({"error": message, "detail": detail, "status": status}, status=status)

    # ----------------------------------------------------------------- verbs
    def do_GET(self):
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.app.log("GET " + self.path + " failed:\n" + traceback.format_exc())
            try:
                self.error(500, "internal error", traceback.format_exc().splitlines()[-1])
            except Exception:
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self.route_post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.app.log("POST " + self.path + " failed:\n" + traceback.format_exc())
            try:
                self.error(500, "internal error", traceback.format_exc().splitlines()[-1])
            except Exception:
                pass

    # ---------------------------------------------------------------- routes
    def route_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        one = lambda k, d=None: (q.get(k) or [d])[0]

        if path.startswith("/api/"):
            return self.api(path, one)
        return self.static(path)

    def api(self, path: str, one):
        st, cfg = self.app.state, self.app.cfg

        if path == "/api/ping":
            return self.json({"ok": True, "version": VERSION, "uptime_s": round(time.time() - self.app.started, 1)})

        if path == "/api/config":
            return self.json(cfg.to_public_dict())

        if path == "/api/summary":
            return self.json(st.summary(), etag=True)

        if path == "/api/agents":
            return self.json({"agents": st.agents(), "ts": iso(now())}, etag=True)

        if path.startswith("/api/agents/"):
            return self.agent_detail(urllib.parse.unquote(path.split("/", 3)[3]))

        if path == "/api/tasks":
            return self.tasks(one)

        if path.startswith("/api/tasks/"):
            return self.task_detail(urllib.parse.unquote(path.split("/", 3)[3]))

        if path == "/api/jobs":
            return self.json({"jobs": [{k: v for k, v in j.items() if k not in ("brief", "handoff")}
                                       for j in st.jobs()]})

        if path.startswith("/api/jobs/"):
            jid = urllib.parse.unquote(path.split("/", 3)[3])
            for j in st.jobs():
                if j["id"] == jid:
                    return self.json(j)
            return self.error(404, "job not found", jid)

        if path == "/api/review":
            return self.json({"queue": st.review(), "ts": iso(now())}, etag=True)

        if path == "/api/channels":
            return self.json({"channels": st.collector.channels()})

        if path == "/api/messages":
            channel = one("channel", "general")
            limit = min(int(one("limit", "80") or 80), 400)
            rows = st.collector.messages(channel=channel, limit=limit, before=one("before"),
                                         mtype=one("type"), search=one("q"))
            return self.json({"channel": channel, "messages": rows, "count": len(rows)})

        if path == "/api/search":
            return self.json(self.search(one("q", "")))

        if path == "/api/wire":
            limit = min(int(one("limit", "120") or 120), 500)
            return self.json({"events": st.collector.wire(limit=limit, repo=one("repo"), search=one("q"))})

        if path == "/api/records":
            kind = one("kind", "pushes")
            limit = min(int(one("limit", "200") or 200), 1000)
            if kind == "shifts":
                return self.json({"kind": kind, "rows": st.collector.shifts(limit=limit, agent=one("agent"))})
            return self.json({"kind": kind, "rows": st.collector.pushes(limit=limit, agent=one("agent"),
                                                                        repo=one("repo"))})

        if path == "/api/activity":
            limit = min(int(one("limit", "120") or 120), 600)
            return self.json({"events": st.collector.activity(st.tasks(), limit=limit)})

        if path == "/api/sources":
            return self.json({"sources": st.source_status(), "sync": st.sync_report,
                              "sync_ts": st.sync_ts, "data_dir": cfg.data_dir})

        if path == "/api/resources":
            return self.json(resources.snapshot(data_dir=cfg.data_dir))

        if path == "/api/github/overview":
            if one("refresh") == "1":
                self.app.github.mem.clear()
            data = self.app.github.overview(CORE_REPOS)
            data["cache_dir"] = str(Path(cfg.data_dir) / "cache" / "github")
            return self.json(data)

        if path == "/api/events":
            return self.sse()

        return self.error(404, "no such endpoint", path)

    # ------------------------------------------------------------------- api
    def tasks(self, one):
        st = self.app.state
        rows = st.tasks()
        status = one("status")
        owner = one("owner")
        q = (one("q") or "").lower()
        if status and status != "all":
            wanted = set(status.split(","))
            rows = [t for t in rows if t.get("status") in wanted]
        if owner:
            rows = [t for t in rows if (t.get("owner") or "") == owner]
        if q:
            rows = [t for t in rows if q in (t.get("title", "") + " " + t.get("desc", "") +
                                             " " + " ".join(t.get("tags") or []) + " " + t.get("id", "")).lower()]
        rows = sorted(rows, key=lambda t: (t.get("created_ts") or "", t["id"]))
        total = len(rows)
        offset = max(0, int(one("offset", "0") or 0))
        limit = min(int(one("limit", "200") or 200), 500)
        page = rows[offset:offset + limit]

        def trim(t):
            return {k: t.get(k) for k in ("id", "title", "status", "owner", "priority", "tags",
                                          "created_ts", "updated_ts", "pr", "branch", "parent",
                                          "completed_ts", "lease", "created_by")} | {
                "votes": len(t.get("votes") or {}),
                "age_min": _age(t.get("created_ts")),
                "updated_age_min": _age(t.get("updated_ts")),
                "blocked_reason": _blocked_reason(t) if t.get("status") == "blocked" else "",
                "history_len": len(t.get("history") or []),
            }
        return self.json({"tasks": [trim(t) for t in page], "total": total,
                          "offset": offset, "limit": limit,
                          "counts": self.app.state.counts()})

    def task_detail(self, tid: str):
        for t in self.app.state.tasks():
            if t["id"] == tid:
                return self.json(t)
        return self.error(404, "task not found", tid)

    def agent_detail(self, name: str):
        st = self.app.state
        agent = next((a for a in st.agents() if a["name"] == name), None)
        if not agent:
            return self.error(404, "agent not found", name)
        owned = [t for t in st.tasks() if (t.get("owner") or "") == name]
        out = dict(agent)
        out["tasks"] = [{k: t.get(k) for k in ("id", "title", "status", "priority", "updated_ts", "pr")}
                        for t in sorted(owned, key=lambda t: t.get("updated_ts") or "", reverse=True)][:80]
        out["shifts"] = st.collector.shifts(limit=10, agent=name)
        msgs = []
        for ch in ("general", "dev", "managerreports"):
            path = st.sources.file("chatcode", f"bus/{ch}.jsonl")
            if path.exists():
                msgs.extend(st.collector.messages(channel=ch, limit=400, search=None) or [])
        own = [m for m in msgs if m.get("from") == name]
        own.sort(key=lambda m: m.get("ts") or "", reverse=True)
        out["messages"] = own[:25]
        heartbeats = []
        hb = st.sources.file("agency", f"board/heartbeats/{name}.jsonl")
        if hb.exists():
            from .collect import read_jsonl
            heartbeats = read_jsonl(hb)[-30:]
        out["heartbeats"] = heartbeats
        return self.json(out)

    def search(self, q: str):
        st = self.app.state
        q = (q or "").strip()
        if len(q) < 2:
            return {"tasks": [], "agents": [], "messages": [], "wire": [], "query": q}
        ql = q.lower()
        tasks = [{"id": t["id"], "title": t.get("title"), "status": t.get("status"),
                  "owner": t.get("owner")}
                 for t in st.tasks() if ql in (t.get("title", "") + " " + t.get("desc", "")).lower()][:24]
        agents = [{"name": a["name"], "state": a["state"], "role": a.get("role")}
                  for a in st.agents() if ql in (a["name"] + " " + (a.get("caps") or "") + " " +
                                                 (a.get("display") or "")).lower()][:12]
        messages = []
        for ch in ("general", "dev", "human-carlo", "managerreports"):
            for m in st.collector.messages(channel=ch, limit=20, search=q):
                messages.append(m)
        messages.sort(key=lambda m: m.get("ts") or "", reverse=True)
        wire = st.collector.wire(limit=20, search=q)
        return {"tasks": tasks, "agents": agents, "messages": messages[:40],
                "wire": wire, "query": q}

    # ------------------------------------------------------------------- sse
    def sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = self.app.state.subscribe()
        try:
            self.wfile.write(f"event: hello\ndata: {json.dumps({'version': self.app.state.version})}\n\n".encode())
            self.wfile.flush()
            last_ping = time.time()
            while True:
                try:
                    payload = q.get(timeout=15)
                    self.wfile.write(f"event: change\ndata: {payload}\n\n".encode())
                except Exception:
                    pass
                if time.time() - last_ping > 20:
                    self.wfile.write(b": ping\n\n")
                    last_ping = time.time()
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.state.unsubscribe(q)

    # ---------------------------------------------------------------- static
    def static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        base = UI_DIR.resolve()
        target = (base / rel).resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        try:
            st = target.stat()
        except OSError:
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        etag = f'"{int(st.st_mtime)}-{st.st_size}"'
        if self._if_none_match(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ------------------------------------------------------------------ post
    def route_post(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/api/sync", "/api/trigger", "/api/action"):
            return self.route_write(parsed)
        return self.error(404, "no such endpoint", parsed.path)

    def route_write(self, parsed):
        if parsed.path == "/api/sync":
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and host and urllib.parse.urlparse(origin).netloc != host:
                return self.error(403, "cross-origin write refused")
            if self.headers.get("X-AgencyOS") != "1":
                return self.error(403, "missing X-AgencyOS header")
            report = self.app.state.sources.sync()
            self.app.state.sync_report = report
            self.app.state.sync_ts = time.time()
            self.app.state.bump()
            return self.json({"ok": True, "report": report})

        if parsed.path != "/api/action":
            return self.error(404, "no such endpoint", parsed.path)
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if origin and host and urllib.parse.urlparse(origin).netloc != host:
            return self.error(403, "cross-origin write refused")
        if self.headers.get("X-AgencyOS") != "1":
            return self.error(403, "missing X-AgencyOS header")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            return self.error(400, "empty or oversized body")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.error(400, "invalid JSON")
        action = payload.get("action", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self.error(400, "params must be an object")
        try:
            result = self.app.actions.run(action, params)
        except ActionError as exc:
            return self.json({"ok": False, "error": str(exc)}, status=409)
        # a successful write changes the mirror; give the collector the new state
        self.app.state.bump()
        return self.json(result)

    # ------------------------------------------------------------------- tcp
    def address_string(self):
        return self.client_address[0]


def _age(ts) -> float | None:
    d = parse_ts(ts) if isinstance(ts, str) else None
    return round((now() - d).total_seconds() / 60, 1) if d else None


def _blocked_reason(task: dict) -> str:
    for h in reversed(task.get("history") or []):
        if "block" in (h.get("action") or "").lower():
            return h.get("action", "")
    return "no reason recorded"


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, addr, handler, app: App):
        self.app = app
        super().__init__(addr, handler)

    def server_bind(self):
        # Dual-stack where available: the sandbox preview proxies over IPv4.
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        super().server_bind()


def build_server(cfg) -> tuple[Server, App]:
    app = App(cfg)
    Handler.app = app
    server = Server((cfg.host, cfg.port), Handler, app)
    return server, app


def serve(cfg, ready_cb=None):
    server, app = build_server(cfg)
    app.state.start()
    app.log(f"agencyd {VERSION} listening on http://{cfg.host}:{cfg.port} "
            f"(actions={'on' if app.actions.enabled()[0] else 'off'})")
    if ready_cb:
        ready_cb(server, app)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.state.stop()
        server.shutdown()
        app.log("agencyd stopped")
