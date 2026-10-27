"""Collectors: turn real agency repositories into one honest snapshot.

Every function here reads files that exist in the operator's repositories.  If a
source is missing, the snapshot says so (`sources[].present == false`) instead of
substituting sample data.  Nothing is simulated, estimated or "illustrative".

Formats consumed (all verified in the live repositories, 2026-10-27):

  chatcode/board/tasks/<id>.json    one card per task: status, owner, lease, votes, history
  chatcode/agents/<name>.json       roster + last_seen
  chatcode/bus/<channel>.jsonl      append-only messages
  agency/agents/<name>.json         newer roster (lifecycle clock, epoch)
  agency/jobs/<id>/                 BRIEF, PHASES, HANDOFF, STATUS.json, PHASELOG.jsonl, evidence
  agency/board/heartbeats/<n>.jsonl append-only pulses
  agency/ORDERS.md                  the Director's standing orders (single source of truth)
  storagecode/wire/YYYY-MM-DD.jsonl durable archive of the formalcode wire
  storagecode/shifts/*.md           shift notes left by operatives
  storagecode/PUSHES.md             one ledger row per push, every repo
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

QUIET_MIN = 45          # agency law: 45 minutes of board silence = presumed dead
FRESH_MIN = 45
RETIRED_H = 6           # silence past this reads as retired, not merely stalled
OPEN_STATUSES = ("open", "claimed", "review", "blocked")
TASK_STATUSES = ("open", "claimed", "review", "blocked", "done", "dropped")


# --------------------------------------------------------------------- utils
def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def age_minutes(ts: str, ref: datetime | None = None) -> float | None:
    d = parse_ts(ts)
    if not d:
        return None
    return ((ref or now()) - d).total_seconds() / 60.0


def human_age(minutes: float | None) -> str:
    if minutes is None:
        return "never"
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{int(minutes)}m"
    if minutes < 60 * 24:
        return f"{int(minutes // 60)}h {int(minutes % 60):02d}m"
    return f"{int(minutes // 1440)}d {int((minutes % 1440) // 60):02d}h"


def tail_lines(path: Path, n: int) -> list[str]:
    """Last n lines of a file without reading the whole file."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 1 << 20)
            while True:
                fh.seek(size - block)
                data = fh.read(block)
                lines = data.split(b"\n")
                if len(lines) > n + 1 or block >= size:
                    return [l.decode("utf-8", "replace") for l in lines[-n - 1:] if l.strip()]
                block = min(size, block * 4)
    except OSError:
        return []


def read_jsonl(path: Path, limit: int | None = None, newest_first: bool = False) -> list[dict]:
    out = []
    for line in tail_lines(path, limit) if limit else _all_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out)) if newest_first else out


def _all_lines(path: Path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


# ----------------------------------------------------------------- file cache
class FileCache:
    """Per-file cache keyed on (mtime_ns, size). Survives repo syncs."""

    def __init__(self):
        self._json: dict[str, tuple[int, int, object]] = {}
        self._text: dict[str, tuple[int, int, str]] = {}
        self._counts: dict[str, tuple[int, int, int]] = {}

    def json(self, path: Path, default=None):
        try:
            st = path.stat()
        except OSError:
            return default
        key = str(path)
        hit = self._json.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            obj = default
        self._json[key] = (st.st_mtime_ns, st.st_size, obj)
        return obj

    def text(self, path: Path) -> str:
        try:
            st = path.stat()
        except OSError:
            return ""
        key = str(path)
        hit = self._text.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            txt = ""
        self._text[key] = (st.st_mtime_ns, st.st_size, txt)
        return txt

    def line_count(self, path: Path) -> int:
        try:
            st = path.stat()
        except OSError:
            return 0
        key = str(path)
        hit = self._counts.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        n = 0
        try:
            with open(path, "rb") as fh:
                for _ in fh:
                    n += 1
        except OSError:
            return 0
        self._counts[key] = (st.st_mtime_ns, st.st_size, n)
        return n


# ------------------------------------------------------------------ collector
class Collector:
    def __init__(self, sources, cache: FileCache | None = None):
        self.sources = sources
        self.cache = cache or FileCache()

    # -- roster ------------------------------------------------------------
    def load_agents(self) -> list[dict]:
        agents: dict[str, dict] = {}
        for src, d in (("chatcode", "agents"), ("agency", "agents")):
            for p in self.sources.listdir(src, d):
                if p.suffix != ".json":
                    continue
                rec = self.cache.json(p, {}) or {}
                name = (rec.get("name") or p.stem).lower()
                if not name:
                    continue
                entry = agents.setdefault(name, {"name": name})
                entry.update({k: rec.get(k) for k in
                              ("display", "role", "kind", "model", "caps", "note",
                               "status", "joined_ts", "last_seen", "epoch")})
                entry.setdefault("display", name)
                entry.setdefault("kind", "ai")
                entry.setdefault("role", "worker")
                entry.setdefault("sources", [])
                if src not in entry["sources"]:
                    entry["sources"].append(src)
                # agency's roster is newer; keep the freshest last_seen
                if rec.get("last_seen") and (not entry.get("last_seen") or
                                             rec["last_seen"] > entry["last_seen"]):
                    entry["last_seen"] = rec["last_seen"]
        return sorted(agents.values(), key=lambda a: a["name"])

    # -- board -------------------------------------------------------------
    def load_tasks(self) -> list[dict]:
        tasks = []
        for p in self.sources.listdir("chatcode", "board/tasks"):
            if p.suffix != ".json" or p.name.startswith("."):
                continue
            t = self.cache.json(p, None)
            if not isinstance(t, dict) or not t.get("id"):
                continue
            t["source"] = "chatcode"
            t["file"] = p.name
            t["desc"] = (t.get("desc") or "")[:4000]
            tasks.append(t)
        tasks.sort(key=lambda t: (t.get("created_ts") or "", t.get("id") or ""))
        return tasks

    def load_archive(self) -> list[dict]:
        out = []
        for p in self.sources.listdir("chatcode", "board/archive"):
            if p.suffix != ".json":
                continue
            t = self.cache.json(p, None)
            if isinstance(t, dict) and t.get("id"):
                t["source"] = "chatcode-archive"
                out.append(t)
        return out

    def load_jobs(self) -> list[dict]:
        jobs = []
        for d in self.sources.listdir("agency", "jobs"):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            status = self.cache.json(d / "STATUS.json", {}) or {}
            phases_md = self.cache.text(d / "PHASES.md")
            brief = self.cache.text(d / "BRIEF.md")
            handoff = self.cache.text(d / "HANDOFF.md")
            log = read_jsonl(d / "PHASELOG.jsonl") if (d / "PHASELOG.jsonl").exists() else []
            claims = []
            for c in sorted(d.glob("CLAIM.*.json")):
                rec = self.cache.json(c, {}) or {}
                claims.append({"agent": rec.get("agent", c.stem.split(".")[-1]),
                               "ts": rec.get("ts", ""), "lease_hours": rec.get("lease_hours"),
                               "epoch": rec.get("epoch", "")})
            evidence = [p.name for p in (d / "evidence").glob("*")] if (d / "evidence").is_dir() else []
            phases = parse_phases(phases_md)
            job = {
                "id": d.name,
                "title": first_heading(brief) or d.name,
                "status": status.get("status", "open"),
                "owner": status.get("owner") or (claims[-1]["agent"] if claims else None),
                "phase": status.get("phase", ""),
                "updated_ts": status.get("updated_ts", ""),
                "phases": phases,
                "claims": claims,
                "evidence": evidence,
                "phase_log": log[-40:],
                "brief": brief[:6000],
                "handoff": handoff[:6000],
                "source": "agency",
                "path": str(d),
            }
            jobs.append(job)
        return sorted(jobs, key=lambda j: j["id"])

    # -- bus ---------------------------------------------------------------
    def channels(self) -> list[dict]:
        out = []
        for p in self.sources.listdir("chatcode", "bus"):
            if p.suffix != ".jsonl":
                continue
            n = self.cache.line_count(p)
            if not n:
                continue
            last = read_jsonl(p, limit=1)
            out.append({"name": p.stem, "messages": n,
                        "last_ts": last[-1].get("ts", "") if last else "",
                        "kind": ("dm" if p.stem.startswith("dm-") else
                                 "human" if p.stem.startswith("human-") else "channel")})
        out.sort(key=lambda c: (-_epoch(c["last_ts"]), c["name"]))
        return out

    def messages(self, channel: str = "general", limit: int = 120, before: str | None = None,
                 mtype: str | None = None, search: str | None = None) -> list[dict]:
        path = self.sources.file("chatcode", f"bus/{channel}.jsonl")
        if not path.exists():
            return []
        if search:
            rows = _search_jsonl(path, search, limit, channel)
        else:
            rows = []
            for m in read_jsonl(path, limit=min(max(limit * 3, 300), 4000)):
                m["channel"] = channel
                rows.append(m)
            rows = rows[-limit:]
        if mtype:
            rows = [m for m in rows if m.get("type") == mtype]
        if before:
            b = parse_ts(before)
            rows = [m for m in rows if parse_ts(m.get("ts")) and parse_ts(m["ts"]) < b]
        return rows[-limit:]

    # -- storagecode -------------------------------------------------------
    def wire(self, limit: int = 200, repo: str | None = None, search: str | None = None) -> list[dict]:
        rows: list[dict] = []
        files = [p for p in self.sources.listdir("storagecode", "wire") if p.suffix == ".jsonl"]
        for p in reversed(files):
            rows.extend(read_jsonl(p))
            if len(rows) > (limit * 4 if not (repo or search) else 40000):
                break
        out = []
        for r in rows:
            parsed = parse_wire(r)
            if repo and parsed["repo"] != repo:
                continue
            if search and search.lower() not in (parsed["text"] + " " + parsed["author"]).lower():
                continue
            out.append(parsed)
        out.sort(key=lambda r: r["time"], reverse=True)
        return out[:limit]

    def shifts(self, limit: int = 60, agent: str | None = None) -> list[dict]:
        out = []
        for p in sorted(self.sources.listdir("storagecode", "shifts"), reverse=True):
            if p.suffix != ".md" or p.name.startswith("TEMPLATE"):
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", p.name)
            if not m:
                continue
            date, who = m.group(1), m.group(2)
            if agent and who != agent:
                continue
            text = self.cache.text(p)
            out.append({
                "date": date, "agent": who, "file": p.name,
                "title": first_heading(text) or p.stem,
                "excerpt": _first_paragraphs(text, 400),
                "body": text[:20000],
                "url": f"https://github.com/dreamer2664/storagecode/blob/main/shifts/{p.name}",
            })
            if len(out) >= limit:
                break
        return out

    def pushes(self, limit: int = 300, agent: str | None = None, repo: str | None = None) -> list[dict]:
        text = self.sources.read_text("storagecode", "PUSHES.md")
        rows = []
        for line in text.splitlines():
            if not line.startswith("| 20"):
                continue
            parts = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(parts) < 6:
                continue
            date, who, rep, ref, what, nxt = parts[:6]
            if agent and who != agent:
                continue
            if repo and rep != repo:
                continue
            sha = ""
            m = re.search(r"@([0-9a-f]{7,40})", ref)
            if m:
                sha = m.group(1)
            pr = re.search(r"PR #(\d+)", ref)
            rows.append({"date": date, "agent": who, "repo": rep, "ref": ref, "sha": sha,
                         "pr": int(pr.group(1)) if pr else None,
                         "what": what, "next": nxt})
        rows.reverse()
        return rows[:limit]

    # -- orders ------------------------------------------------------------
    def orders(self) -> dict:
        text = self.sources.read_text("agency", "ORDERS.md") or self.sources.read_text("chatcode", "SYSTEM.md")
        if not text:
            return {"epoch": "", "standing": [], "redlines": [], "present": False}
        epoch = ""
        m = re.search(r"EPOCH:\s*([0-9][^\s·|]*)", text)
        if m:
            epoch = m.group(1)
        standing = _section_items(text, "Standing orders")
        red = _section_items(text, "Red lines")
        return {"epoch": epoch, "standing": standing, "redlines": red, "present": True,
                "url": "https://github.com/dreamer2664/agency/blob/main/ORDERS.md"}

    # -- derived state -----------------------------------------------------
    def agent_states(self, tasks: list[dict], agents: list[dict], ref: datetime | None = None) -> list[dict]:
        ref = ref or now()
        by_owner: dict[str, list[dict]] = {}
        for t in tasks:
            if t.get("owner") and t.get("status") in OPEN_STATUSES:
                by_owner.setdefault(t["owner"], []).append(t)
        out = []
        for a in agents:
            name = a["name"]
            held = by_owner.get(name, [])
            leased = [t for t in held if _lease_active(t, ref)]
            blocked = [t for t in held if t.get("status") == "blocked"]
            reviewing = [t for t in held if t.get("status") == "review"]
            last_seen = a.get("last_seen") or ""
            seen_min = age_minutes(last_seen, ref)
            # an agent is alive only if something it touched moved recently
            # an expired lease is not a sign of life: only fresh board writes count
            activity = max([x for x in (last_seen, _latest_task_ts(held, ref)) if x] or [""])
            act_min = age_minutes(activity, ref)
            if act_min is None:
                state = "unknown"
            elif act_min <= FRESH_MIN:
                state = "working" if (leased or [t for t in held if t.get("status") == "claimed"]) else (
                    "blocked" if blocked else "idle")
            elif act_min <= RETIRED_H * 60:
                state = "stalled"
            else:
                state = "retired"
            if state in ("working", "idle", "blocked") and leased:
                state = "working"
            clock = life_clock(seen_min)
            out.append({
                **{k: a.get(k) for k in ("name", "display", "role", "kind", "model", "caps",
                                         "note", "status", "joined_ts", "last_seen", "epoch", "sources")},
                "state": state,
                "silence_min": act_min,
                "silence": human_age(act_min),
                "life_clock": clock,
                "held": [{"id": t["id"], "title": t.get("title", ""), "status": t.get("status"),
                          "lease": t.get("lease")} for t in held],
                "blocked": [{"id": t["id"], "title": t.get("title"), "reason": _block_reason(t)}
                            for t in blocked],
                "in_review": [t["id"] for t in reviewing],
                "lease_active": bool(leased),
                "lease_expired": bool([t for t in held if t.get("lease") and not _lease_active(t, ref)]),
            })
        order = {"working": 0, "idle": 1, "blocked": 2, "unknown": 3, "stalled": 4, "retired": 5}
        out.sort(key=lambda a: (order.get(a["state"], 9), -(a["silence_min"] or 0)))
        return out

    def review_queue(self, tasks: list[dict], ref: datetime | None = None) -> list[dict]:
        ref = ref or now()
        out = []
        for t in tasks:
            if t.get("status") != "review":
                continue
            votes = t.get("votes") or {}
            accepted = [v for v in votes.values() if v.get("vote") == "accept" and v.get("inspected")]
            denied = [v for v in votes.values() if v.get("vote") == "deny"]
            non_owner = [v for v in votes.values() if True]
            need = max(0, 2 - len(accepted))
            reviewed_by = list(votes.keys())
            out.append({
                "id": t["id"], "title": t.get("title", ""), "owner": t.get("owner"),
                "pr": t.get("pr"), "branch": t.get("branch"),
                "age_min": age_minutes(t.get("updated_ts") or t.get("created_ts"), ref),
                "accepts": len(accepted), "denies": len(denied),
                "reviewers": reviewed_by, "need": need,
                "quorum": need == 0,
                "blocked_by": [x for x in reviewed_by if not votes[x].get("inspected")],
                "votes": sorted([{"agent": k, **v} for k, v in votes.items()],
                                key=lambda v: v.get("ts", "")),
            })
        out.sort(key=lambda r: (r["quorum"], -len(r["reviewers"]), -(r["age_min"] or 0)))
        return out

    def board_counts(self, tasks: list[dict]) -> dict:
        c = {s: 0 for s in TASK_STATUSES}
        for t in tasks:
            s = t.get("status")
            if s in c:
                c[s] += 1
        c["total"] = len(tasks)
        c["live"] = sum(c[s] for s in OPEN_STATUSES)
        return c

    # -- unified timeline --------------------------------------------------
    def activity(self, tasks: list[dict], limit: int = 400) -> list[dict]:
        events = []
        for w in self.wire(limit=limit):
            events.append({"ts": w["ts"], "time": w["time"], "kind": "wire", "actor": w["author"],
                           "repo": w["repo"], "text": w["text"], "url": w["url"], "icon": "wire"})
        for p in self.pushes(limit=150):
            events.append({"ts": p["date"] + "T00:00:00Z", "time": _epoch(p["date"] + "T00:00:00Z"),
                           "kind": "push", "actor": p["agent"], "repo": p["repo"],
                           "text": p["what"][:300], "url": _commit_url(p["repo"], p["sha"]), "icon": "push"})
        for t in tasks:
            for h in (t.get("history") or [])[-6:]:
                ts = h.get("ts", "")
                events.append({"ts": ts, "time": _epoch(ts), "kind": "task", "actor": h.get("by", ""),
                               "repo": "chatcode", "text": f"{t['id']} · {t.get('title','')[:120]} — {h.get('action','')}",
                               "url": f"https://github.com/dreamer2664/chatcode/blob/main/board/tasks/{t['id']}.json",
                               "icon": "task"})
        for s in self.shifts(limit=40):
            events.append({"ts": s["date"] + "T00:00:00Z", "time": _epoch(s["date"] + "T00:00:00Z"),
                           "kind": "shift", "actor": s["agent"], "repo": "storagecode",
                           "text": s["title"], "url": s["url"], "icon": "shift"})
        events.sort(key=lambda e: e["time"], reverse=True)
        return events[:limit]

    # -- alerts / next actions --------------------------------------------
    def alerts(self, agents: list[dict], tasks: list[dict], counts: dict, jobs: list[dict],
               ref: datetime | None = None) -> list[dict]:
        ref = ref or now()
        alerts = []
        alive = [a for a in agents if a["state"] in ("working", "idle", "blocked")]
        if not alive and agents:
            alerts.append({"severity": "critical", "kind": "dormant",
                           "text": f"No operative is alive. {counts['live']} live cards and "
                                   f"{counts['open']} unclaimed tasks are waiting.",
                           "action": "assign work or restaff the board"})
        stale_leases = [t for t in tasks if t.get("lease") and t.get("status") in ("claimed", "blocked")
                        and not _lease_active(t, ref)]
        if stale_leases:
            alerts.append({"severity": "warn", "kind": "lease",
                           "text": f"{len(stale_leases)} expired lease(s) still hold cards — "
                                   f"`chatcode tasks sweep --apply` returns them to the pool.",
                           "refs": [t["id"] for t in stale_leases[:12]]})
        quorum_ready = [t for t in tasks if t.get("status") == "review" and _quorum(t)]
        if quorum_ready:
            alerts.append({"severity": "info", "kind": "review",
                           "text": f"{len(quorum_ready)} review(s) already have two inspected accept votes — "
                                   f"merge or close them.", "refs": [t["id"] for t in quorum_ready[:12]]})
        blocked = [t for t in tasks if t.get("status") == "blocked"]
        if blocked:
            alerts.append({"severity": "warn", "kind": "blocked",
                           "text": f"{len(blocked)} card(s) marked blocked. A block without a written reason "
                                   f"is a protocol violation.", "refs": [t["id"] for t in blocked[:12]]})
        idle = [a for a in agents if a["state"] == "idle"]
        if idle:
            alerts.append({"severity": "info", "kind": "idle",
                           "text": f"{len(idle)} operative(s) are awake with no lease: "
                                   f"{', '.join(a['name'] for a in idle[:6])}.",
                           "action": "hand out the next approved card"})
        claimed_jobs = [j for j in jobs if j["status"] == "claimed"]
        for j in claimed_jobs:
            ts = j.get("updated_ts")
            age = age_minutes(ts, ref)
            if age and age > QUIET_MIN:
                alerts.append({"severity": "warn", "kind": "job",
                               "text": f"Job {j['id']} is held by {j['owner']} with no update for {human_age(age)}.",
                               "refs": [j["id"]]})
        return alerts

    def next_actions(self, agents: list[dict], counts: dict, review: list[dict],
                     orders: dict, ref: datetime | None = None) -> list[dict]:
        ref = ref or now()
        acts = []
        alive = [a for a in agents if a["state"] in ("working", "idle", "blocked")]
        unclaimed = counts.get("open", 0)
        if counts.get("review"):
            acts.append({"priority": 1, "title": f"Clear the review queue ({counts['review']})",
                         "detail": "Two inspected, non-owner accept votes close a card. Reviewing is "
                                   "background work every operative does between builds.",
                         "command": "python3 bin/chatcode review next"})
        if unclaimed and alive:
            acts.append({"priority": 2, "title": f"Hand the {unclaimed} open cards to the live crew",
                         "detail": "Idle operatives must claim the next approved card or report that they "
                                   "need an assignment. Silence is not a status.",
                         "command": "python3 bin/chatcode tasks list --status open"})
        if counts.get("open") and not alive:
            acts.append({"priority": 1, "title": "The board has work and nobody to do it",
                         "detail": f"{counts['open']} unclaimed cards, 0 operatives alive. Start a session "
                                   "and claim one, or the queue is a museum.",
                         "command": "python3 bin/chatcode tasks list --status open --json"})
        if not unclaimed and not counts.get("review"):
            acts.append({"priority": 1, "title": "Queue empty — do not invent work",
                         "detail": "No open cards and nothing in review. Either a manager cuts the next "
                                   "approved card, or the agency is honestly idle. Say so on the wire.",
                         "command": "python3 bin/chatcode say \"queue empty — idle, no assignment\" --type status"})
        if orders.get("standing"):
            acts.append({"priority": 3, "title": f"Directive in force (epoch {orders.get('epoch') or '—'})",
                         "detail": orders["standing"][0][:240],
                         "command": "cat agency/ORDERS.md"})
        return acts


# ---------------------------------------------------------------- helpers
def _epoch(ts: str) -> float:
    d = parse_ts(ts)
    return d.timestamp() if d else 0.0


def _lease_active(task: dict, ref: datetime) -> bool:
    lease = task.get("lease") or {}
    exp = parse_ts(lease.get("expires"))
    return bool(exp and exp > ref)


def _lease_expired(task: dict, ref: datetime) -> bool:
    lease = task.get("lease") or {}
    exp = parse_ts(lease.get("expires"))
    return bool(exp and exp <= ref)


def _quorum(task: dict) -> bool:
    votes = task.get("votes") or {}
    return len([v for v in votes.values() if v.get("vote") == "accept" and v.get("inspected")]) >= 2


def _latest_task_ts(tasks: list[dict], ref: datetime | None = None) -> str:
    ref = ref or now()
    ts = ""
    for t in tasks:
        lease = t.get("lease")
        if lease and not _lease_active(t, ref):
            continue
        for cand in (t.get("updated_ts"),
                     (t.get("history") or [{}])[-1].get("ts") if t.get("history") else ""):
            if cand and cand > ts:
                ts = cand
    return ts


def _block_reason(task: dict) -> str:
    hist = task.get("history") or []
    for h in reversed(hist):
        if "block" in (h.get("action") or "").lower():
            return h.get("action", "")
    return "no reason recorded"


def life_clock(silence_min: float | None) -> str:
    if silence_min is None:
        return "UNKNOWN"
    h = silence_min / 60
    if h < 6:
        return "ROOKIE"
    if h < 48:
        return "FULL"
    if h < 60:
        return "AGING"
    return "RETIRED"


def parse_phases(md: str) -> list[dict]:
    rows = []
    for line in md.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue
        if cells[0].lower().startswith("phase"):
            continue
        if re.match(r"^P\d", cells[0], re.I):
            rows.append({"phase": cells[0], "deliverable": cells[1],
                         "evidence": cells[2] if len(cells) > 2 else "",
                         "min_hours": cells[3] if len(cells) > 3 else ""})
    return rows


def first_heading(md: str) -> str:
    for line in md.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
        if line.strip():
            return line.strip()[:120]
    return ""


def _first_paragraphs(md: str, n: int) -> str:
    out = []
    for line in md.splitlines():
        if line.startswith("#"):
            continue
        if line.strip():
            out.append(line.strip())
        elif out:
            break
    return " ".join(out)[:n]


def _section_items(md: str, heading: str) -> list[str]:
    items, inside = [], False
    for line in md.splitlines():
        if line.startswith("#"):
            if inside:
                break
            if heading.lower() in line.lower():
                inside = True
            continue
        if not inside:
            continue
        m = re.match(r"^\s*(?:\d+\.|[-*])\s+(.*)$", line)
        if m:
            items.append(m.group(1).strip())
    return items


def _search_jsonl(path: Path, needle: str, limit: int, channel: str) -> list[dict]:
    """Bounded search: stream the file, keep the newest `limit` matches."""
    needle = needle.lower()
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if needle not in line.lower():
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                m["channel"] = channel
                out.append(m)
                if len(out) > limit * 4:
                    out = out[-limit * 2:]
    except OSError:
        return []
    return out[-limit:]


def parse_wire(raw: dict) -> dict:
    msg = raw.get("message") or ""
    repo, author, text, url = "", "", msg, ""
    m = re.match(r"^\[([^\]]+)\]\s*(.*)$", msg)
    if m:
        repo, rest = m.group(1), m.group(2)
        parts = [p.strip() for p in rest.split("·")]
        if len(parts) >= 2:
            author = parts[1]
            text = " · ".join(parts[2:]) if len(parts) > 2 else rest
        else:
            text = rest
    mu = re.search(r"(https://github\.com/\S+)", msg)
    if mu:
        url = mu.group(1).rstrip(".,)")
        text = text.replace(mu.group(0), "").strip(" ·")
    t = raw.get("time") or 0
    return {
        "id": raw.get("id", ""),
        "time": t,
        "ts": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else "",
        "topic": raw.get("topic", ""),
        "repo": repo,
        "author": author,
        "text": text,
        "url": url,
    }


def _commit_url(repo: str, sha: str) -> str:
    known = {"chatcode", "agency", "storagecode", "lightship", "vigil", "superocr", "sable",
             "pc-eye", "glowmoth", "floodline", "frameforge", "buildinglab", "chesseye",
             "zugzwang", "neurobrain", "agent-atlas", "mars", "storage"}
    r = repo if repo in known else repo
    return f"https://github.com/dreamer2664/{r}/commit/{sha}" if sha else f"https://github.com/dreamer2664/{r}"
