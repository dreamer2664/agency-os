"""agencyos — the command line that operates the deck.

    agencyos up            start the daemon in the background
    agencyos status        is it alive, on which port, against which mirrors
    agencyos doctor        every dependency and source, with the fix
    agencyos sync          fetch the mirrors (never destructive)
    agencyos measure       real RSS numbers, optionally with a browser attached
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .config import (CONFIG_PATH, VERSION, Config, ensure_dirs, load_config, save_config)
from .resources import footprint, meminfo

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------- utils
def human_mb(kb: float) -> str:
    return f"{kb / 1024:.1f} MB"


def pid_path(cfg: Config) -> Path:
    return Path(cfg.home) / "run" / "agencyd.pid"


def log_path(cfg: Config) -> Path:
    return Path(cfg.home) / "log" / "agencyd.log"


def read_pid(cfg: Config) -> int | None:
    p = pid_path(cfg)
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def runtime_path(cfg: Config) -> Path:
    return Path(cfg.home) / "run" / "state.json"


def write_runtime(cfg: Config, pid: int, port: int) -> None:
    """Remember what was actually started, so `status`/`open` never guess the port."""
    p = runtime_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({"pid": pid, "port": port, "host": cfg.host,
                                 "started": time.time()}), encoding="utf-8")
    except OSError:
        pass


def read_runtime(cfg: Config) -> dict:
    try:
        raw = json.loads(runtime_path(cfg).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def drop_runtime(cfg: Config) -> None:
    try:
        runtime_path(cfg).unlink()
    except OSError:
        pass


def http_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def local_url(cfg: Config, port: int | None = None) -> str:
    host = "127.0.0.1" if cfg.host in ("0.0.0.0", "::") else cfg.host
    if port is None:
        port = int(read_runtime(cfg).get("port") or cfg.port)
    return f"http://{host}:{port}"


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1" if host in ("0.0.0.0", "::") else host, port))
            return True
        except OSError:
            return False


def fmt_table(rows: list[tuple], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    line = "  ".join(h.upper().ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


# ------------------------------------------------------------------ commands
def cmd_run(args) -> int:
    from .server import serve
    cfg = load_config(args.config)
    if args.port:
        cfg.port = args.port
    if args.host:
        cfg.host = args.host
    if args.allow_actions:
        cfg.allow_actions = True
    if args.no_sync:
        cfg.sync_on_start = False
        cfg.sync_interval = 0
    if args.sync_interval is not None:
        cfg.sync_interval = args.sync_interval
    ensure_dirs(cfg)
    if not port_free(cfg.host, cfg.port):
        print(f"port {cfg.port} is already in use — stop the other process or pass --port N",
              file=sys.stderr)
        return 2

    def ready(server, app):
        pid_path(cfg).write_text(str(os.getpid()))
        write_runtime(cfg, os.getpid(), cfg.port)
        print(f"Agency OS {VERSION} · {local_url(cfg, cfg.port)} · pid {os.getpid()}")
        print(f"  data   {cfg.data_dir}")
        print(f"  log    {log_path(cfg)}")
        print(f"  write  {'ENABLED' if app.actions.enabled()[0] else 'disabled (read-only)'}")
        sys.stdout.flush()

    try:
        serve(cfg, ready_cb=ready)
    finally:
        try:
            pid_path(cfg).unlink()
        except OSError:
            pass
        drop_runtime(cfg)
    return 0


def cmd_up(args) -> int:
    cfg = load_config(args.config)
    if args.port:
        cfg.port = args.port
    ensure_dirs(cfg)
    pid = read_pid(cfg)
    if pid:
        print(f"already running (pid {pid}) · {local_url(cfg)}")
        return 0
    if not port_free(cfg.host, cfg.port):
        print(f"port {cfg.port} is already in use — another daemon may be running; "
              f"try `agencyos up --port {cfg.port + 1}`", file=sys.stderr)
        return 2
    lp = log_path(cfg)
    lp.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "agencyd.cli", "run", "--port", str(cfg.port),
           "--host", cfg.host]
    if args.config:
        cmd += ["--config", str(args.config)]
    if args.allow_actions:
        cmd.append("--allow-actions")
    if args.no_sync:
        cmd.append("--no-sync")
    with open(lp, "ab") as log:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log,
                                start_new_session=True, close_fds=True)
    for _ in range(60):
        time.sleep(0.1)
        try:
            info = http_json(local_url(cfg, cfg.port) + "/api/ping")
            write_runtime(cfg, proc.pid, cfg.port)
            print(f"Agency OS {VERSION} up · {local_url(cfg, cfg.port)} · pid {proc.pid}")
            print(f"log: {lp}")
            return 0
        except Exception:
            if proc.poll() is not None:
                break
    print("failed to start — last log lines:", file=sys.stderr)
    try:
        print("\n".join(lp.read_text().splitlines()[-12:]), file=sys.stderr)
    except OSError:
        pass
    return 1


def cmd_down(args) -> int:
    cfg = load_config(args.config)
    pid = read_pid(cfg)
    if not pid:
        print("not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"could not signal {pid}: {exc}", file=sys.stderr)
        return 1
    for _ in range(50):
        time.sleep(0.1)
        if read_pid(cfg) is None:
            drop_runtime(cfg)
            try:
                pid_path(cfg).unlink()
            except OSError:
                pass
            print("stopped")
            return 0
    try:
        os.kill(pid, signal.SIGKILL)
        print("killed after timeout")
    except OSError:
        pass
    return 0


def cmd_status(args) -> int:
    cfg = load_config(args.config)
    pid = read_pid(cfg)
    print(f"Agency OS {VERSION}")
    print(f"  config   {args.config or CONFIG_PATH}")
    print(f"  data     {cfg.data_dir}")
    print(f"  process  {'pid ' + str(pid) if pid else 'not running'}")
    if not pid:
        # Do not present someone else's daemon as this installation's.
        url = local_url(cfg)
        try:
            info = http_json(url + "/api/ping", timeout=2)
            print(f"  http     {url} answers (uptime {info['uptime_s']}s) — started elsewhere, "
                  f"not by this install")
            print(f"  hint     agencyos up --port {cfg.port + 1}")
        except Exception:
            print("  http     not listening")
        return 0
    try:
        info = http_json(local_url(cfg) + "/api/ping")
        summ = http_json(local_url(cfg) + "/api/summary", timeout=6)
        print(f"  http     {local_url(cfg)} (up {info['uptime_s']}s)")
        b, a = summ["board"], summ["agents"]
        print(f"  board    {b['open']} open · {b['claimed']} claimed · {b['review']} review · "
              f"{b['blocked']} blocked · {b['done']} done")
        print(f"  crew     {a['alive']} alive / {a['total']} total · status {summ['status']['label']}")
        fp = footprint(pid) if pid else None
        if fp:
            print(f"  memory   {fp['rss_mb']} MB RSS / {fp['pss_mb']} MB PSS "
                  f"across {fp['count']} process(es)")
        print(f"  sources  " + ", ".join(
            f"{s['name']}@{s['head'] or '—'}{'' if s['present'] else ' (missing)'}"
            for s in summ["sources"]))
    except Exception as exc:
        print(f"  http     unreachable ({exc.__class__.__name__})")
    return 0


def cmd_sync(args) -> int:
    cfg = load_config(args.config)
    from .sources import Sources
    ensure_dirs(cfg)
    src = Sources(cfg, logger=lambda m: print("[sync]", m))
    report = src.sync(only=args.only.split(",") if args.only else None)
    rows = [(r["name"], r["action"], r["detail"], r["head"] or "-") for r in report]
    print(fmt_table(rows, ["source", "action", "detail", "head"]))
    if any(not r["ok"] for r in report):
        return 1
    # tell a running daemon to re-read immediately
    if read_pid(cfg):
        try:
            urllib.request.urlopen(urllib.request.Request(
                local_url(cfg) + "/api/trigger", method="POST"), timeout=3)
        except Exception:
            pass
    return 0


def cmd_doctor(args) -> int:
    cfg = load_config(args.config)
    checks: list[tuple[str, bool, str]] = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    py = sys.version_info
    add("python", py >= (3, 10), f"{py.major}.{py.minor}.{py.micro} (>=3.10 required)")
    add("git", bool(shutil.which("git")), shutil.which("git") or "missing — mirrors cannot sync")
    add("ui assets", (ROOT / "ui" / "index.html").is_file(), str(ROOT / "ui"))
    try:
        cfg.data_dir and Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        test = Path(cfg.data_dir) / ".write-test"
        test.write_text("x")
        test.unlink()
        add("data dir", True, cfg.data_dir)
    except OSError as exc:
        add("data dir", False, f"{cfg.data_dir}: {exc}")
    from .sources import Sources
    src = Sources(cfg)
    for row in src.status():
        add(f"source:{row['name']}", row["present"],
            f"{row['path']} {('@' + row['head']) if row['head'] else ''}".strip() +
            ("" if row["present"] else " — run `agencyos sync`"))
    add("token", cfg.has_token(),
        "present (not printed)" if cfg.has_token()
        else "absent — read-only mode; export GITHUB_PAT to enable private repos and writes")
    acts_ok, acts_why = cfg.allow_actions, "requested" if cfg.allow_actions else "off"
    add("write mode", True, f"{acts_ok and 'enabled' or 'disabled'} ({acts_why})")
    add("port", port_free(cfg.host, cfg.port), f"{cfg.host}:{cfg.port}")
    mem = meminfo()
    add("memory", mem.get("total_kb", 0) > 900_000,
        f"{human_mb(mem.get('total_kb', 0))} total, {human_mb(mem.get('available_kb', 0))} available")
    add("browser", bool(find_browser()), find_browser() or "none found (deck still works in any browser)")
    width = max(len(c[0]) for c in checks)
    bad = 0
    for name, ok, detail in checks:
        mark = "ok  " if ok else "MISS"
        if not ok:
            bad += 1
        print(f"[{mark}] {name.ljust(width)}  {detail}")
    print()
    print("all good" if bad == 0 else f"{bad} item(s) need attention")
    return 0


def cmd_sources(args) -> int:
    cfg = load_config(args.config)
    from .sources import Sources
    rows = [(s["name"], s["repo"], s["head"] or "-", s["head_date"][:19], "yes" if s["present"] else "NO")
            for s in Sources(cfg).status()]
    print(fmt_table(rows, ["source", "repo", "head", "committed", "present"]))
    return 0


def find_browser() -> str:
    for b in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
              "firefox", "epiphany", "brave-browser", "microsoft-edge"):
        p = shutil.which(b)
        if p:
            return p
    return ""


def cmd_measure(args) -> int:
    cfg = load_config(args.config)
    pid = read_pid(cfg)
    url = args.url or local_url(cfg)
    base = {
        "daemon_pid": pid,
        "url": url,
        "system_memory": meminfo(),
    }
    if pid:
        base["daemon"] = footprint(pid)
    print(json.dumps({k: v for k, v in base.items() if k != "daemon"}, indent=2))
    if base.get("daemon"):
        print(f"agencyd tree RSS: {base['daemon']['rss_mb']} MB · PSS: {base['daemon']['pss_mb']} MB "
              f"across {base['daemon']['count']} process(es)")
    if not args.browser:
        return 0
    browser = find_browser()
    if not browser:
        print("no browser found — install chromium to measure the full stack", file=sys.stderr)
        return 1
    import tempfile
    profile = tempfile.mkdtemp(prefix="agencyos-measure-")
    flags = [browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
             f"--user-data-dir={profile}", "--window-size=1440,900", "--hide-scrollbars",
             "--disable-extensions", "--no-first-run", "--no-default-browser-check",
             "--run-all-compositor-stages-before-draw", "--virtual-time-budget=8000",
             "--screenshot=" + str(Path(cfg.home) / "run" / "measure.png"), url]
    if args.seconds:
        flags = [f for f in flags if not f.startswith("--virtual-time-budget")]
    proc = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    samples = []
    t0 = time.time()
    duration = args.seconds or 12
    while time.time() - t0 < duration and proc.poll() is None:
        time.sleep(0.4)
        if pid:
            d = footprint(pid)["rss_kb"]
        else:
            d = 0
        b = footprint_of_tree(proc.pid, "pss")
        br = footprint_of_tree(proc.pid, "rss")
        samples.append((d, b, meminfo().get("available_kb", 0), br))
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        pass
    if samples:
        peak = max(samples, key=lambda s: s[0] + s[1])
        mid = sorted(samples, key=lambda s: s[0] + s[1])[len(samples) // 2]
        report = {
            "samples": len(samples),
            "peak": {"daemon_mb": round(peak[0] / 1024, 1), "browser_pss_mb": round(peak[1] / 1024, 1),
                     "browser_rss_sum_mb": round(peak[3] / 1024, 1),
                     "total_pss_mb": round((peak[0] + peak[1]) / 1024, 1),
                     "available_mb": round(peak[2] / 1024, 1)},
            "median": {"daemon_mb": round(mid[0] / 1024, 1), "browser_pss_mb": round(mid[1] / 1024, 1),
                       "total_pss_mb": round((mid[0] + mid[1]) / 1024, 1)},
            "note": "PSS divides shared pages between sharers, so it is the honest total for a "
                    "multi-process browser. browser_rss_sum_mb is the raw (double-counting) upper bound.",
            "browser": browser,
            "profile": profile,
        }
        print(json.dumps(report, indent=2))
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    return 0


def footprint_of_tree(root_pid: int, metric: str = "pss") -> int:
    """Memory (kB) of a process tree using /proc, tolerant of fast exits.

    metric="pss" divides shared pages between sharers (the honest number for a
    browser, whose helper processes map the same binaries); metric="rss" is the
    raw upper bound and double-counts them.
    """
    from .resources import proc_table
    table = proc_table()
    kids: dict[int, list[int]] = {}
    for pid, row in table.items():
        kids.setdefault(row["ppid"], []).append(pid)
    total, stack, seen = 0, [root_pid], set()
    while stack:
        p = stack.pop()
        if p in seen or p not in table:
            continue
        seen.add(p)
        if metric == "rss":
            total += table[p]["rss_kb"]
        else:
            try:
                with open(f"/proc/{p}/smaps_rollup", "r") as fh:
                    for line in fh:
                        if line.startswith("Pss:"):
                            total += int(line.split()[1])
                            break
                    else:
                        total += table[p]["rss_kb"]
            except (OSError, ValueError):
                total += table[p]["rss_kb"]
        stack.extend(kids.get(p, []))
    return total


def cmd_config(args) -> int:
    cfg = load_config(args.config)
    if args.set:
        for pair in args.set:
            if "=" not in pair:
                print(f"ignoring {pair!r} (expected key=value)", file=sys.stderr)
                continue
            k, v = pair.split("=", 1)
            if not hasattr(cfg, k) or k.startswith("_"):
                print(f"unknown key {k!r}", file=sys.stderr)
                continue
            cur = getattr(cfg, k)
            try:
                setattr(cfg, k, type(cur)(v))
            except (TypeError, ValueError):
                print(f"bad value for {k}: {v!r}", file=sys.stderr)
                continue
        p = save_config(cfg, args.config)
        print(f"wrote {p}")
        return 0
    print(json.dumps(cfg.to_public_dict(), indent=2))
    print(f"config file: {args.config or CONFIG_PATH}"
          f"{'' if Path(args.config or CONFIG_PATH).exists() else ' (not created yet)'}")
    return 0


def cmd_logs(args) -> int:
    cfg = load_config(args.config)
    p = log_path(cfg)
    if not p.exists():
        print(f"no log yet at {p}")
        return 0
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if args.follow:
        pos = p.stat().st_size
        print("\n".join(lines[-args.lines:]))
        try:
            while True:
                time.sleep(0.7)
                size = p.stat().st_size
                if size < pos:
                    pos = 0
                if size > pos:
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        sys.stdout.write(fh.read())
                        sys.stdout.flush()
                    pos = size
        except KeyboardInterrupt:
            return 0
    print("\n".join(lines[-args.lines:]))
    return 0


def cmd_kiosk(args) -> int:
    """Hand the session to scripts/kiosk.sh (Xvfb + fullscreen browser)."""
    script = ROOT / "scripts" / "kiosk.sh"
    if not script.exists():
        print("scripts/kiosk.sh is missing from this checkout", file=sys.stderr)
        return 1
    cmd = ["bash", str(script), "--port", str(args.port), "--browser", args.browser]
    if args.size:
        cmd += ["--size", args.size]
    if args.display:
        cmd += ["--display", args.display]
    return subprocess.call(cmd)


def cmd_open(args) -> int:
    cfg = load_config(args.config)
    url = local_url(cfg)
    try:
        http_json(url + "/api/ping")
    except Exception:
        print("daemon is not running — `agencyos up` first", file=sys.stderr)
        return 1
    import webbrowser
    if not webbrowser.open(url):
        print(f"open {url} in your browser")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agencyos", description="Agency OS control surface")
    ap.add_argument("--config", help="path to config.json")
    ap.add_argument("--version", action="version", version=f"agency-os {VERSION}")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="run the daemon in the foreground")
    p.add_argument("--port", type=int)
    p.add_argument("--host")
    p.add_argument("--allow-actions", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--sync-interval", type=int)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("up", help="start in the background")
    p.add_argument("--port", type=int)
    p.add_argument("--allow-actions", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p.set_defaults(fn=cmd_up)

    for name, fn, helptext in (("down", cmd_down, "stop the daemon"),
                               ("status", cmd_status, "show daemon and agency status"),
                               ("doctor", cmd_doctor, "check dependencies and sources"),
                               ("sources", cmd_sources, "list repository mirrors"),
                               ("open", cmd_open, "open the deck in a browser")):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(fn=fn)

    p = sub.add_parser("sync", help="fetch the repository mirrors")
    p.add_argument("--only", help="comma separated source names")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("kiosk", help="run the deck fullscreen (Xvfb + chromium/firefox)")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--browser", default="chromium", choices=["chromium", "firefox"])
    p.add_argument("--size", default="1440x900")
    p.add_argument("--display", help="use an existing X display instead of Xvfb")
    p.set_defaults(fn=cmd_kiosk)

    p = sub.add_parser("measure", help="measure real memory usage")
    p.add_argument("--browser", action="store_true", help="also launch a headless browser")
    p.add_argument("--kiosk", action="store_true", help="measure the kiosk configuration")
    p.add_argument("--seconds", type=int, default=12)
    p.add_argument("--url")
    p.add_argument("--json", help="write the report to this path")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("config", help="show or change configuration")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("logs", help="show the daemon log")
    p.add_argument("--lines", type=int, default=60)
    p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(fn=cmd_logs)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        return 0
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
