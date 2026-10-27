"""In-process state: caches, change detection, and the SSE fan-out.

One watcher thread polls a cheap filesystem signature (directory mtimes) every
few seconds.  When it moves, every connected browser is told to re-fetch — there
is no per-client polling, and no timer that rebuilds anything that did not
change.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .collect import Collector, FileCache, now, iso
from .sources import Sources


class State:
    def __init__(self, cfg, logger=None):
        self.cfg = cfg
        self.log = logger or (lambda *a, **k: None)
        self.sources = Sources(cfg, logger=self.log)
        self.collector = Collector(self.sources, FileCache())
        self.version = 1
        self.signature = self.sources.signature()
        self.started = time.time()
        self.last_change = time.time()
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[int, object]] = {}
        self._subs: list[queue.Queue] = []
        self._stop = threading.Event()
        self.sync_report: list[dict] = []
        self.sync_ts = 0.0
        self.threads: list[threading.Thread] = []
        self.github = None  # set by server once configured

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self.cfg.sync_on_start:
            t = threading.Thread(target=self._initial_sync, name="agencyos-sync", daemon=True)
            t.start()
            self.threads.append(t)
        t = threading.Thread(target=self._watch, name="agencyos-watch", daemon=True)
        t.start()
        self.threads.append(t)
        if self.cfg.sync_interval > 0:
            t = threading.Thread(target=self._sync_loop, name="agencyos-pull", daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self._stop.set()

    def _initial_sync(self):
        try:
            self.sync_report = self.sources.sync()
            self.sync_ts = time.time()
            self.bump()
        except Exception as exc:  # never take the daemon down for a network hiccup
            self.log(f"initial sync failed: {exc.__class__.__name__}: {exc}")

    def _sync_loop(self):
        while not self._stop.wait(max(30, self.cfg.sync_interval)):
            try:
                self.sync_report = self.sources.sync()
                self.sync_ts = time.time()
            except Exception as exc:
                self.log(f"sync failed: {exc.__class__.__name__}: {exc}")

    def _watch(self):
        while not self._stop.wait(self.cfg.watch_interval):
            try:
                sig = self.sources.signature()
            except Exception:
                continue
            if sig != self.signature:
                self.signature = sig
                self.bump()

    def bump(self):
        with self._lock:
            self.version += 1
            self.last_change = time.time()
            self._cache.clear()
        payload = json.dumps({"version": self.version, "ts": iso(now())})
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    # ------------------------------------------------------------------ sse
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=16)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    # ---------------------------------------------------------------- cache
    def cached(self, key: str, builder):
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == self.version:
                return hit[1]
        value = builder()
        with self._lock:
            self._cache[key] = (self.version, value)
        return value

    # ------------------------------------------------------------ snapshots
    def agents(self):
        return self.cached("agents", lambda: self.collector.agent_states(
            self.collector.load_tasks(), self.collector.load_agents()))

    def tasks(self):
        return self.cached("tasks", self.collector.load_tasks)

    def jobs(self):
        return self.cached("jobs", self.collector.load_jobs)

    def review(self):
        return self.cached("review", lambda: self.collector.review_queue(self.tasks()))

    def counts(self):
        return self.cached("counts", lambda: self.collector.board_counts(self.tasks()))

    def orders(self):
        return self.cached("orders", self.collector.orders)

    def summary(self) -> dict:
        def build():
            agents = self.agents()
            counts = self.counts()
            jobs = self.jobs()
            review = self.review()
            orders = self.orders()
            wire = self.collector.wire(limit=400)
            day_ago = time.time() - 86400
            leases = [t for t in self.tasks() if t.get("lease")]
            active_leases = [t for t in leases if t["lease"].get("expires")
                             and (t["lease"]["expires"] or "") > iso(now())]
            alive = [a for a in agents if a["state"] in ("working", "idle", "blocked")]
            return {
                "generated_ts": iso(now()),
                "generated_epoch": time.time(),
                "version": self.version,
                "status": self._org_status(alive, counts, agents),
                "board": counts,
                "agents": {
                    "total": len(agents),
                    "alive": len(alive),
                    "working": len([a for a in agents if a["state"] == "working"]),
                    "idle": len([a for a in agents if a["state"] == "idle"]),
                    "blocked": len([a for a in agents if a["state"] == "blocked"]),
                    "retired": len([a for a in agents if a["state"] == "retired"]),
                    "stalled": len([a for a in agents if a["state"] == "stalled"]),
                },
                "leases": {"total": len(leases), "active": len(active_leases),
                           "expired": len(leases) - len(active_leases)},
                "review": {"count": counts.get("review", 0),
                           "quorum_ready": len([r for r in review if r["quorum"]])},
                "jobs": {"total": len(jobs),
                         "claimed": len([j for j in jobs if j["status"] == "claimed"]),
                         "open": len([j for j in jobs if j["status"] == "open"])},
                "last_activity_ts": _last_activity(agents, wire),
                "wire": {"total": len(wire),
                         "last_24h": len([w for w in wire if w["time"] >= day_ago]),
                         "last_ts": wire[0]["ts"] if wire else ""},
                "orders": {"epoch": orders.get("epoch", ""),
                           "standing": orders.get("standing", [])[:6],
                           "redlines": orders.get("redlines", [])[:8],
                           "present": orders.get("present", False)},
                "alerts": self.collector.alerts(agents, self.tasks(), counts, jobs),
                "next_actions": self.collector.next_actions(agents, counts, review, orders),
                "sources": self.source_status(),
            }
        return self.cached("summary", build)

    def _org_status(self, alive, counts, agents) -> dict:
        if not agents:
            return {"code": "unconfigured", "label": "NO ROSTER",
                    "detail": "No agents/ directory found in the configured sources."}
        if not alive:
            last = max([a.get("last_seen") or "" for a in agents] or [""])
            return {"code": "dormant", "label": "DORMANT",
                    "detail": f"0 operatives alive · last sign of life {last or 'unknown'} · "
                              f"{counts.get('live', 0)} live cards waiting"}
        blocked = [a for a in alive if a["state"] == "blocked"]
        if blocked:
            return {"code": "degraded", "label": "DEGRADED",
                    "detail": f"{len(blocked)} operative(s) blocked · {len(alive)} alive"}
        return {"code": "operational", "label": "OPERATIONAL",
                "detail": f"{len(alive)} alive · {counts.get('claimed', 0)} leased · "
                          f"{counts.get('review', 0)} awaiting review"}

    def source_status(self) -> list[dict]:
        out = []
        for row in self.sources.status():
            row["stale"] = bool(row["head_date"]) and (
                (now().timestamp() - _ts(row["head_date"])) > 7 * 86400)
            out.append(row)
        return out


def _last_activity(agents, wire) -> str:
    """The newest timestamp anywhere: roster, board leases, or the wire."""
    candidates = [a.get("last_seen") or "" for a in agents]
    candidates += [w.get("ts") or "" for w in wire[:30]]
    return max([c for c in candidates if c] or [""])


def _ts(iso_str: str) -> float:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return time.time()
