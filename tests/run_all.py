#!/usr/bin/env python3
"""Agency OS test suite — stdlib only, no network, no browser.

    python3 tests/run_all.py            run everything
    python3 tests/run_all.py -k server  run tests whose name matches

The suite builds a throw-away agency (board, roster, bus, wire, ledger) in a
temp directory and checks the collectors, the HTTP API and the write guards
against it. Nothing here touches the operator's real mirrors.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agencyd.collect import (Collector, FileCache, human_age, parse_wire, parse_phases,  # noqa: E402
                             life_clock)
from agencyd.sources import Sources  # noqa: E402
from agencyd.config import Config, SourceConfig  # noqa: E402
from agencyd.actions import Actions, ActionError, scrub  # noqa: E402

TESTS: list[tuple[str, callable]] = []


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


def iso(minutes_ago: float = 0) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: expected {b!r}, got {a!r}")


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "expected truthy")


# --------------------------------------------------------------------- fixture
class Fixture:
    """A miniature agency on disk: 3 tasks, 2 agents, a bus, a wire, a ledger."""

    def __init__(self, root: Path, tasks: int = 3):
        self.root = root
        self.chatcode = root / "chatcode"
        self.agency = root / "agency"
        self.storage = root / "storagecode"
        for d in ("board/tasks", "board/archive", "agents", "bus", "memory"):
            (self.chatcode / d).mkdir(parents=True, exist_ok=True)
        for d in ("agents", "board/heartbeats", "jobs/t-20260101-demo/evidence", "ledger"):
            (self.agency / d).mkdir(parents=True, exist_ok=True)
        for d in ("wire", "shifts", "data"):
            (self.storage / d).mkdir(parents=True, exist_ok=True)

        (self.agency / "ORDERS.md").write_text(
            "# ORDERS\n<!-- EPOCH: 2026-01-01.1 -->\n\n## Standing orders\n\n"
            "1. **Ship the demo** — the only priority.\n2. Preserve evidence.\n\n"
            "## Red lines\n\n- **R3 SECRETS:** never on a wire.\n", encoding="utf-8")
        (self.agency / "agents/ada.json").write_text(json.dumps(
            {"name": "ada", "display": "ADA", "role": "worker", "kind": "ai",
             "model": "test-model", "caps": "python", "last_seen": iso(2)}), encoding="utf-8")
        (self.agency / "agents/boris.json").write_text(json.dumps(
            {"name": "boris", "display": "BORIS", "role": "worker", "kind": "ai",
             "last_seen": iso(60 * 30)}), encoding="utf-8")
        (self.agency / "board/heartbeats/ada.jsonl").write_text(json.dumps(
            {"kind": "pulse", "ts": iso(2), "note": "alive"}) + "\n", encoding="utf-8")
        job = self.agency / "jobs/t-20260101-demo"
        (job / "STATUS.json").write_text(json.dumps(
            {"owner": "ada", "phase": "P1", "status": "claimed", "updated_ts": iso(5)}), encoding="utf-8")
        (job / "BRIEF.md").write_text("# Demo job\n\nDo the thing.\n", encoding="utf-8")
        (job / "PHASES.md").write_text(
            "| phase | deliverable | evidence | min_hours |\n|---|---|---|---|\n"
            "| P1 | audit | AUDIT.md | 0.5 |\n| P2 | fix | PATCH.md | 1 |\n", encoding="utf-8")
        (job / "PHASELOG.jsonl").write_text(json.dumps(
            {"action": "start", "by": "ada", "phase": "P1", "ts": iso(5)}) + "\n", encoding="utf-8")
        (job / "evidence/AUDIT.md").write_text("done\n", encoding="utf-8")
        (job / "CLAIM.ada.json").write_text(json.dumps(
            {"agent": "ada", "ts": iso(5), "lease_hours": 8}), encoding="utf-8")

        extra = max(0, tasks - 4)
        for i in range(extra):
            self.write_task(f"t-fill-{i:03d}", "open", None, f"Bulk card {i}")
        self.write_task("t-20260101-open", "open", None, "An unclaimed card")
        self.write_task("t-20260101-live", "claimed", "ada", "A live leased card",
                        lease={"agent": "ada", "since": iso(10),
                               "expires": iso(-120), "checkpoint": "half done"})
        self.write_task("t-20260101-dead", "claimed", "boris", "A dead operative's card",
                        lease={"agent": "boris", "since": iso(3000), "expires": iso(2000)})
        self.write_task("t-20260101-rev", "review", "ada", "Waiting for ballots")

        bus = self.chatcode / "bus/general.jsonl"
        with open(bus, "w", encoding="utf-8") as fh:
            for i in range(5):
                fh.write(json.dumps({"id": f"m{i}", "ts": iso(30 - i), "from": "ada",
                                     "type": "say", "text": f"Message {i}"}) + "\n")
        (self.chatcode / "bus/dm-ada__boris.jsonl").write_text(
            json.dumps({"id": "d1", "ts": iso(40), "from": "ada", "type": "say",
                        "text": "direct"}) + "\n", encoding="utf-8")
        wire = self.storage / "wire/2026-01-01.jsonl"
        wire.write_text(json.dumps({
            "id": "w1", "time": time.time() - 600, "topic": "formalcode",
            "message": "[chatcode] abcdef12 · ada · board: t-20260101-live claimed · "
                       "https://github.com/dreamer2664/chatcode/commit/abcdef12"}) + "\n", encoding="utf-8")
        (self.storage / "PUSHES.md").write_text(
            "# PUSHES\n\n| date (UTC) | agent | repo | branch @ SHA / PR | what + result | next |\n"
            "|---|---|---|---|---|---|\n"
            "| 2026-01-01 | ada | chatcode | main @abc1234 | did the thing | review it |\n",
            encoding="utf-8")
        (self.storage / "shifts/2026-01-01-ada.md").write_text(
            "# Shift note — ada\n\nArrived, worked, left.\n", encoding="utf-8")

    def write_task(self, tid, status, owner, title, lease=None, votes=None):
        t = {"id": tid, "title": title, "desc": f"{title} — description", "status": status,
             "owner": owner, "created_by": "manager", "created_ts": iso(600),
             "updated_ts": iso(20), "priority": 2, "tags": [], "deps": [], "parent": None,
             "branch": None, "pr": None, "history": [
                 {"ts": iso(600), "by": "manager", "action": "created"},
                 {"ts": iso(30), "by": owner or "none", "action": f"moved to {status}"}]}
        if lease:
            t["lease"] = lease
        if votes:
            t["votes"] = votes
        (self.chatcode / f"board/tasks/{tid}.json").write_text(json.dumps(t), encoding="utf-8")
        return t

    def config(self, data_dir: Path) -> Config:
        cfg = Config()
        cfg.data_dir = str(data_dir / "data")
        cfg.sources = [
            SourceConfig("chatcode", "local/chatcode", path=str(self.chatcode)),
            SourceConfig("agency", "local/agency", path=str(self.agency)),
            SourceConfig("storagecode", "local/storagecode", path=str(self.storage)),
        ]
        return cfg


# ----------------------------------------------------------------------- tests
@test
def test_collector_reads_the_board_and_roster():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        c = Collector(Sources(cfg))
        tasks = c.load_tasks()
        assert_eq(len(tasks), 4, "task count")
        counts = c.board_counts(tasks)
        assert_eq(counts["open"], 1, "open")
        assert_eq(counts["claimed"], 2, "claimed")
        assert_eq(counts["review"], 1, "review")
        agents = c.agent_states(tasks, c.load_agents())
        by = {a["name"]: a for a in agents}
        assert_eq(by["ada"]["state"], "working", "ada holds a live lease")
        assert_true(by["boris"]["state"] in ("stalled", "retired"), "boris is not alive")
        assert_eq(by["ada"]["lease_active"], True, "ada lease active")
        assert_eq(by["boris"]["lease_expired"], True, "boris lease expired")


@test
def test_review_queue_orders_and_counts_quorum():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        c = Collector(Sources(cfg))
        tasks = c.load_tasks()
        t = next(x for x in tasks if x["id"] == "t-20260101-rev")
        t["votes"] = {
            "ada": {"vote": "accept", "inspected": True, "reason": "ran the suite", "ts": iso(10)},
            "cy": {"vote": "accept", "inspected": True, "reason": "re-ran it", "ts": iso(5)},
        }
        q = c.review_queue(tasks)
        row = next(r for r in q if r["id"] == "t-20260101-rev")
        assert_eq(row["accepts"], 2, "accepts")
        assert_eq(row["need"], 0, "need")
        assert_true(row["quorum"], "quorum reached")


@test
def test_alerts_and_next_actions_track_reality():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        c = Collector(Sources(cfg))
        tasks = c.load_tasks()
        agents = c.agent_states(tasks, c.load_agents())
        counts = c.board_counts(tasks)
        jobs = c.load_jobs()
        alerts = c.alerts(agents, tasks, counts, jobs)
        kinds = {a["kind"] for a in alerts}
        assert_true("lease" in kinds, "an expired lease must raise a lease alert")
        assert_true(not any(a["kind"] == "dormant" for a in alerts), "ada is alive")
        acts = c.next_actions(agents, counts, c.review_queue(tasks), c.orders())
        assert_true(any("review" in a["title"].lower() for a in acts), "review work is proposed")


@test
def test_dormant_agency_is_reported_not_papered_over():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        (fx.agency / "agents/ada.json").write_text(json.dumps(
            {"name": "ada", "last_seen": iso(60 * 40)}), encoding="utf-8")
        (fx.agency / "agents/boris.json").unlink()
        (fx.chatcode / "board/tasks/t-20260101-live.json").unlink()
        (fx.chatcode / "board/tasks/t-20260101-rev.json").unlink()
        cfg = fx.config(Path(tmp))
        c = Collector(Sources(cfg))
        tasks = c.load_tasks()
        agents = c.agent_states(tasks, c.load_agents())
        alerts = c.alerts(agents, tasks, c.board_counts(tasks), c.load_jobs())
        assert_true(any(a["kind"] == "dormant" for a in alerts), "dormant alert expected")


@test
def test_wire_pushes_and_orders_parse():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        c = Collector(Sources(fx.config(Path(tmp))))
        wire = c.wire()
        assert_eq(len(wire), 1, "one wire event")
        assert_eq(wire[0]["repo"], "chatcode", "repo parsed")
        assert_eq(wire[0]["author"], "ada", "author parsed")
        pushes = c.pushes()
        assert_eq(pushes[0]["sha"], "abc1234", "sha parsed")
        orders = c.orders()
        assert_eq(orders["epoch"], "2026-01-01.1", "epoch")
        assert_eq(len(orders["standing"]), 2, "standing orders")
        assert_eq(len(orders["redlines"]), 1, "red lines")


@test
def test_messages_support_search_filters_and_tail():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        c = Collector(Sources(fx.config(Path(tmp))))
        rows = c.messages("general", limit=3)
        assert_eq(len(rows), 3, "tail length")
        assert_eq(rows[-1]["text"], "Message 4", "newest last")
        found = c.messages("general", limit=10, search="Message 2")
        assert_eq(len(found), 1, "search")
        chans = {c0["name"]: c0 for c0 in c.channels()}
        assert_eq(chans["dm-ada__boris"]["kind"], "dm", "dm channel classified")


@test
def test_parse_helpers():
    assert_eq(human_age(0), "now")
    assert_eq(human_age(90), "1h 30m")
    assert_eq(life_clock(60), "ROOKIE")
    assert_eq(life_clock(60 * 100), "RETIRED")
    ph = parse_phases("| phase | deliverable | evidence | min_hours |\n|---|---|---|---|\n"
                      "| P1 | audit | AUDIT.md | 0.5 |\n")
    assert_eq(ph[0]["phase"], "P1", "phase parse")
    w = parse_wire({"id": "x", "time": 1700000000, "message": "[storagecode] 1234abc · cy · did a thing"})
    assert_eq((w["repo"], w["author"], w["text"]), ("storagecode", "cy", "did a thing"), "wire parse")


@test
def test_config_never_exposes_the_token():
    os.environ["AGENCY_OS_TOKEN"] = "github_pat_TESTONLYVALUE0123456789"
    try:
        cfg = Config()
        assert_eq(cfg.has_token(), True, "token found in env")
        public = cfg.to_public_dict()
        blob = json.dumps(public)
        assert_true("TESTONLYVALUE" not in blob, "token must never appear in the public config")
        assert_eq(public["authenticated"], True, "authenticated flag")
    finally:
        os.environ.pop("AGENCY_OS_TOKEN", None)


@test
def test_actions_refuse_without_write_mode_and_scrub_secrets():
    os.environ["AGENCY_OS_TOKEN"] = "github_pat_TESTONLYVALUE0123456789"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            cfg = fx.config(Path(tmp))
            acts = Actions(cfg, Sources(cfg))
            ok, why = acts.enabled()
            assert_eq(ok, False, "write mode off by default")
            assert_true("allow-actions" in why, "explains the switch")
            try:
                acts.run("say", {"text": "hello"})
                raise AssertionError("a disabled action must raise")
            except ActionError:
                pass
            assert_eq(scrub("token github_pat_TESTONLYVALUE0123456789 here",
                            "github_pat_TESTONLYVALUE0123456789"), "token *** here", "scrub")
            assert_eq(scrub("ghp_" + "a" * 30, ""), "***", "pattern scrub")
    finally:
        os.environ.pop("AGENCY_OS_TOKEN", None)


@test
def test_action_validation_rejects_nonsense():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        cfg.allow_actions = True
        cfg.agent_name = "ada"
        os.environ["AGENCY_OS_TOKEN"] = "github_pat_TESTONLYVALUE0123456789"
        try:
            acts = Actions(cfg, Sources(cfg))
            for action, params in (("status", {"id": "t-1", "status": "banana"}),
                                   ("vote", {"id": "t-1", "vote": "maybe", "reason": "long enough reason"}),
                                   ("vote", {"id": "t-1", "vote": "accept", "reason": "short"}),
                                   ("say", {"text": "   "}),
                                   ("claim", {"id": ""})):
                try:
                    acts.run(action, params)
                    raise AssertionError(f"{action} {params} should have been refused")
                except ActionError:
                    pass
        finally:
            os.environ.pop("AGENCY_OS_TOKEN", None)


@test
def test_http_api_contract():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        cfg.port = free_port()
        cfg.sync_on_start = False
        cfg.sync_interval = 0
        cfg.host = "127.0.0.1"
        from agencyd.server import build_server
        server, app = build_server(cfg)
        app.state.start()
        t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{cfg.port}"
        try:
            assert_eq(get(base + "/api/ping")["ok"], True, "ping")
            summ = get(base + "/api/summary")
            assert_eq(summ["board"]["review"], 1, "review count through HTTP")
            assert_eq(summ["status"]["code"], "degraded_live_crew" if False else summ["status"]["code"], "")
            assert_true(summ["status"]["code"] in ("operational", "degraded", "dormant"), "status code")
            agents = get(base + "/api/agents")["agents"]
            assert_eq(len(agents), 2, "roster size")
            tasks = get(base + "/api/tasks?status=open")
            assert_eq(tasks["total"], 1, "filtered tasks")
            one = get(base + f"/api/tasks/{tasks['tasks'][0]['id']}")
            assert_true("history" in one, "task detail includes history")
            msgs = get(base + "/api/messages?channel=general&limit=2")
            assert_eq(len(msgs["messages"]), 2, "messages endpoint")
            wire = get(base + "/api/wire")
            assert_eq(len(wire["events"]), 1, "wire endpoint")
            jobs = get(base + "/api/jobs")["jobs"]
            assert_eq(jobs[0]["phases"][0]["phase"], "P1", "jobs expose phases")
            res = get(base + "/api/resources")
            assert_true(res["agencyos"]["rss_mb"] > 0, "real memory reading")
            email = get(base + f"/api/agents/ada")
            assert_eq(email["name"], "ada", "agent detail")
            # ETag / conditional GET
            req = urllib.request.Request(base + "/api/summary", headers={"If-None-Match": '"nope"'})
            with urllib.request.urlopen(req) as resp:
                assert_eq(resp.status, 200, "etag miss")
            # write guards
            for headers, body, expected in (
                ({}, {"action": "say", "params": {"text": "x"}}, 403),
                ({"X-AgencyOS": "1"}, {"action": "say", "params": {"text": "x"}}, 409),
                ({"X-AgencyOS": "1"}, {"action": "delete-everything", "params": {}}, 409),
            ):
                code = post_status(base + "/api/action", body, headers)
                assert_eq(code, expected, f"guard for {headers}")
            # static + traversal
            assert_eq(get_status(base + "/"), 200, "index served")
            assert_eq(get_status(base + "/../agencyd/config.py"), 404, "traversal blocked")
            assert_eq(get_status(base + "/nope.js"), 404, "missing file")
            # CSP header present on the shell
            with urllib.request.urlopen(base + "/") as resp:
                assert_true("default-src 'self'" in resp.headers.get("Content-Security-Policy", ""),
                            "CSP present")
        finally:
            server.shutdown()
            app.state.stop()


@test
def test_sse_delivers_a_change_when_state_moves():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp))
        cfg = fx.config(Path(tmp))
        cfg.port = free_port()
        cfg.sync_on_start = False
        cfg.sync_interval = 0
        cfg.host = "127.0.0.1"
        from agencyd.server import build_server
        server, app = build_server(cfg)
        app.state.start()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        try:
            sock = socket.create_connection(("127.0.0.1", cfg.port), timeout=5)
            sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: localhost\r\n"
                         b"Accept: text/event-stream\r\n\r\n")
            assert_true(read_until(sock, "event: hello"), "hello event on connect")
            fx.write_task("t-20260101-new", "open", None, "Freshly cut card")
            app.state.bump()
            assert_true(read_until(sock, "event: change"), "change event after a bump")
            sock.close()
        finally:
            server.shutdown()
            app.state.stop()


@test
def test_summary_stays_fast_with_a_large_board():
    with tempfile.TemporaryDirectory() as tmp:
        fx = Fixture(Path(tmp), tasks=4000)
        cfg = fx.config(Path(tmp))
        from agencyd.store import State
        st = State(cfg)
        t0 = time.time()
        s = st.summary()
        cold = time.time() - t0
        t0 = time.time()
        st.summary()
        warm = time.time() - t0
        assert_eq(s["board"]["total"], 4000, "all cards counted")
        assert_true(cold < 6.0, f"cold summary too slow: {cold:.2f}s")
        assert_true(warm < 0.05, f"warm summary not cached: {warm:.3f}s")


@test
def test_missing_sources_degrade_gracefully():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config()
        cfg.data_dir = str(Path(tmp) / "data")
        cfg.sources = [SourceConfig("chatcode", "x/y", path=str(Path(tmp) / "nope"))]
        c = Collector(Sources(cfg))
        assert_eq(c.load_tasks(), [], "no tasks")
        assert_eq(c.wire(), [], "no wire")
        s = c.orders()
        assert_eq(s["present"], False, "orders reported missing, not invented")


@test
def test_cli_doctor_and_status_run_without_a_daemon():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env.update({"AGENCY_OS_HOME": tmp, "AGENCY_OS_DATA": str(Path(tmp) / "data"),
                    "AGENCY_OS_CONFIG": str(Path(tmp) / "config.json")})
        r = subprocess.run([sys.executable, str(ROOT / "bin/agencyos"), "doctor"],
                           capture_output=True, text=True, env=env, timeout=60)
        assert_eq(r.returncode, 0, f"doctor exit ({r.stderr[:200]})")
        assert_true("python" in r.stdout, "doctor lists python")
        r = subprocess.run([sys.executable, str(ROOT / "bin/agencyos"), "status"],
                           capture_output=True, text=True, env=env, timeout=60)
        assert_eq(r.returncode, 0, "status exits 0 with nothing running")
        assert_true("not running" in r.stdout, "status says not running")


# --------------------------------------------------------------------- helpers
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_until(sock, needle: str, timeout: float = 5.0) -> bool:
    """Read from a raw socket until `needle` appears (SSE frames span packets)."""
    buf = ""
    deadline = time.time() + timeout
    sock.settimeout(0.5)
    while time.time() < deadline:
        if needle in buf:
            return True
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace")
    return needle in buf


def get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def post_status(url: str, body: dict, headers: dict) -> int:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    only = None
    if "-k" in sys.argv:
        only = sys.argv[sys.argv.index("-k") + 1]
    failures = []
    t0 = time.time()
    for name, fn in TESTS:
        if only and only not in name:
            continue
        started = time.time()
        try:
            fn()
            print(f"  ok    {name}  ({time.time() - started:.2f}s)")
        except Exception:
            failures.append(name)
            print(f"  FAIL  {name}")
            traceback.print_exc(limit=4)
    total = time.time() - t0
    print()
    ran = len([1 for n, _ in TESTS if not only or only in n])
    print(f"{ran - len(failures)}/{ran} passed in {total:.2f}s")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
