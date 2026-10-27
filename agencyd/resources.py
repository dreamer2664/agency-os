"""Real resource measurements, read from /proc. No estimates, no invented gauges."""
from __future__ import annotations

import os
import time
from pathlib import Path


def meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                out[k] = int(parts[0])  # kB
    except (OSError, ValueError):
        return {}
    total = out.get("MemTotal", 0)
    avail = out.get("MemAvailable", 0)
    return {
        "total_kb": total,
        "available_kb": avail,
        "used_kb": max(0, total - avail),
        "used_pct": round(100 * (total - avail) / total, 1) if total else 0.0,
        "swap_total_kb": out.get("SwapTotal", 0),
    }


def loadavg() -> dict:
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        one = five = fifteen = 0.0
    return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2),
            "cpus": os.cpu_count() or 1}


def disk(path: str) -> dict:
    try:
        st = os.statvfs(path)
        size = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return {"path": path, "total": size, "free": free,
                "used_pct": round(100 * (size - free) / size, 1) if size else 0.0}
    except OSError:
        return {"path": path, "total": 0, "free": 0, "used_pct": 0.0}


def proc_table() -> dict[int, dict]:
    """pid -> {ppid, rss_kb, cmd, state} for every visible process."""
    table = {}
    proc = Path("/proc")
    try:
        entries = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return table
    for p in entries:
        try:
            stat = (p / "stat").read_text()
            close = stat.rfind(")")
            fields = stat[close + 2:].split()
            ppid = int(fields[1])
            state = fields[0]
            rss_pages = int(fields[21])
            cmd = (p / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        except (OSError, ValueError, IndexError):
            continue
        table[int(p.name)] = {
            "ppid": ppid,
            "rss_kb": rss_pages * (os.sysconf("SC_PAGE_SIZE") // 1024),
            "state": state,
            "cmd": cmd[:200] or f"[{p.name}]",
        }
    return table


def pss_kb(pid: int) -> int | None:
    """Proportional set size: shared pages are divided between sharers, so a
    summed PSS across a process tree does not double-count shared libraries."""
    try:
        with open(f"/proc/{pid}/smaps_rollup", "r") as fh:
            for line in fh:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def tree(root_pid: int) -> list[dict]:
    table = proc_table()
    kids: dict[int, list[int]] = {}
    for pid, row in table.items():
        kids.setdefault(row["ppid"], []).append(pid)
    out, stack = [], [root_pid]
    seen = set()
    while stack:
        pid = stack.pop()
        if pid in seen or pid not in table:
            continue
        seen.add(pid)
        row = table[pid]
        pss = pss_kb(pid)
        out.append({"pid": pid, **row, "pss_kb": pss if pss is not None else row["rss_kb"]})
        stack.extend(kids.get(pid, []))
    out.sort(key=lambda r: -r["rss_kb"])
    return out


def footprint(root_pid: int | None = None) -> dict:
    """RSS of the Agency OS process tree, summed and per-process."""
    root_pid = root_pid or os.getpid()
    rows = tree(root_pid)
    total = sum(r["rss_kb"] for r in rows)
    pss = sum(r["pss_kb"] for r in rows)
    return {
        "pid": root_pid,
        "processes": rows,
        "count": len(rows),
        "rss_kb": total,
        "rss_mb": round(total / 1024, 1),
        "pss_kb": pss,
        "pss_mb": round(pss / 1024, 1),
    }


def snapshot(root_pid: int | None = None, data_dir: str = ".") -> dict:
    fp = footprint(root_pid)
    mem = meminfo()
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime_s": _uptime(),
        "memory": mem,
        "load": loadavg(),
        "disk": disk(data_dir),
        "agencyos": fp,
        "share_of_ram_pct": round(100 * fp["rss_kb"] / mem["total_kb"], 2) if mem.get("total_kb") else 0.0,
    }


def _uptime() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return 0.0


def measure_command(argv: list[str]) -> dict:
    """Run a command and report its peak RSS (from /proc wait status)."""
    import resource
    import subprocess
    t0 = time.time()
    r = subprocess.run(argv, capture_output=True, text=True)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"argv": argv, "exit": r.returncode, "seconds": round(time.time() - t0, 2),
            "max_rss_mb": round(usage.ru_maxrss / 1024, 1),
            "stdout": r.stdout[-4000:], "stderr": r.stderr[-2000:]}
