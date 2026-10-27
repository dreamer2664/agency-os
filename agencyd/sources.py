"""Local mirrors of the agency's repositories.

Agency OS never invents data: everything it shows is read from a git checkout
of a real agency repository, or from the GitHub API.  Mirrors are *read-only*
for the collector; only `sync()` touches them, and only with fast-forward
fetches (a dirty tree is reported, never discarded).

Clones are blobless + sparse so a 105 MB repo costs a few MB on disk: the deck
only needs the board, the roster, the bus and the ledger, not the artwork.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT = 120


def which_git() -> str | None:
    return shutil.which("git")


def run_git(args: list[str], cwd: str | Path | None = None, timeout: int = GIT_TIMEOUT,
            env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    e.setdefault("GIT_LFS_SKIP_SMUDGE", "1")
    if env:
        e.update(env)
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout, env=e)


@dataclass
class Mirror:
    name: str
    repo: str
    path: Path
    sparse: list

    @property
    def exists(self) -> bool:
        return (self.path / ".git").exists()

    def head(self) -> str:
        """Abbreviated HEAD SHA, or '' when unavailable. Cheap and cached."""
        if not self.exists:
            return ""
        try:
            r = subprocess.run(["git", "-C", str(self.path), "rev-parse", "--short=10", "HEAD"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def head_date(self) -> str:
        if not self.exists:
            return ""
        try:
            r = subprocess.run(["git", "-C", str(self.path), "log", "-1", "--format=%cI"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def dirty(self) -> bool:
        if not self.exists:
            return False
        try:
            r = subprocess.run(["git", "-C", str(self.path), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=15)
            return bool(r.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            return False


class Sources:
    def __init__(self, cfg, logger=None):
        self.cfg = cfg
        self.log = logger or (lambda *a, **k: None)
        self.mirrors: dict[str, Mirror] = {}
        for s in cfg.sources:
            if not s.enabled:
                continue
            path = Path(s.path) if s.path else Path(cfg.data_dir) / "src" / s.name
            self.mirrors[s.name] = Mirror(s.name, s.repo, path, list(s.sparse))
        self._cache: dict = {}

    # ------------------------------------------------------------------ state
    def status(self) -> list[dict]:
        out = []
        for name, m in self.mirrors.items():
            out.append({
                "name": name,
                "repo": m.repo,
                "path": str(m.path),
                "present": m.exists,
                "head": m.head() if m.exists else "",
                "head_date": m.head_date() if m.exists else "",
                "dirty": m.dirty() if m.exists else False,
            })
        return out

    def get(self, name: str) -> Mirror | None:
        return self.mirrors.get(name)

    # ------------------------------------------------------------------ clone
    def clone(self, name: str) -> tuple[bool, str]:
        m = self.mirrors.get(name)
        if not m:
            return False, f"unknown source {name}"
        if m.exists:
            return True, "already present"
        if not which_git():
            return False, "git is not installed"
        m.path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{m.repo}.git"
        base = ["clone", "--depth", "1", "--filter=blob:none", "--single-branch"]
        if m.sparse:
            base += ["--sparse"]
        try:
            r = run_git([*base, url, str(m.path)])
        except subprocess.TimeoutExpired:
            return False, "git clone timed out"
        if r.returncode != 0:
            # blob filters are unsupported on some servers/proxies: fall back
            shutil.rmtree(m.path, ignore_errors=True)
            try:
                r = run_git(["clone", "--depth", "1", "--single-branch", url, str(m.path)])
            except subprocess.TimeoutExpired:
                return False, "git clone timed out"
            if r.returncode != 0:
                return False, (r.stderr or r.stdout).strip().splitlines()[-1:] and \
                    (r.stderr or r.stdout).strip().splitlines()[-1] or "git clone failed"
        if m.sparse and (m.path / ".git").exists():
            try:
                run_git(["sparse-checkout", "set", "--no-cone", *m.sparse], cwd=m.path)
            except subprocess.TimeoutExpired:
                pass
        return True, "cloned"

    # ------------------------------------------------------------------- sync
    def sync(self, only: list[str] | None = None, pull: bool = True) -> list[dict]:
        """Fetch and fast-forward every mirror. Never destructive.

        Returns one report row per source: {name, ok, action, detail, head}.
        """
        reports = []
        for name, m in self.mirrors.items():
            if only and name not in only:
                continue
            if not m.exists:
                ok, detail = self.clone(name)
                reports.append({"name": name, "ok": ok, "action": "clone",
                                "detail": detail, "head": m.head() if ok else ""})
                continue
            if not pull:
                reports.append({"name": name, "ok": True, "action": "none",
                                "detail": "pull disabled", "head": m.head()})
                continue
            if m.dirty():
                reports.append({"name": name, "ok": True, "action": "skipped",
                                "detail": "working tree is dirty — left untouched", "head": m.head()})
                continue
            before = m.head()
            try:
                r = run_git(["pull", "--ff-only", "--depth", "1", "-q"], cwd=m.path)
            except subprocess.TimeoutExpired:
                reports.append({"name": name, "ok": False, "action": "pull",
                                "detail": "timed out", "head": before})
                continue
            after = m.head()
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip().splitlines()
                reports.append({"name": name, "ok": False, "action": "pull",
                                "detail": (detail[-1] if detail else "pull failed"),
                                "head": before})
            else:
                changed = before != after
                reports.append({"name": name, "ok": True,
                                "action": "updated" if changed else "none",
                                "detail": f"{before} -> {after}" if changed else "up to date",
                                "head": after})
        if reports:
            self.log("sync: " + "; ".join(f"{r['name']}={r['action']}({r['detail']})" for r in reports))
        return reports

    # ------------------------------------------------------------------ files
    def file(self, source: str, rel: str) -> Path:
        return self.get(source).path / rel if self.get(source) else Path(rel)

    def read_text(self, source: str, rel: str, limit: int | None = None) -> str:
        p = self.file(source, rel)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read() if limit is None else fh.read(limit)
        except OSError:
            return ""

    def listdir(self, source: str, rel: str) -> list[Path]:
        p = self.file(source, rel)
        try:
            return sorted(p.iterdir())
        except OSError:
            return []

    def signature(self) -> str:
        """A cheap fingerprint of the data the deck renders.

        Uses directory mtimes plus the size/mtime of the hottest files.  When it
        changes, caches are dropped and connected browsers are told to re-fetch.
        Runs in a few milliseconds even with hundreds of board cards.
        """
        h = []
        for name, m in self.mirrors.items():
            if not m.exists:
                h.append((name, 0))
                continue
            for rel in ("board", "board/tasks", "agents", "bus", "wire", "shifts",
                        "jobs", "memory", "data"):
                p = m.path / rel
                try:
                    st = p.stat()
                    h.append((name + "/" + rel, st.st_mtime_ns))
                except OSError:
                    continue
            for rel in ("PUSHES.md", "ORDERS.md", "TOWER.md", "STATUS.md", ".git/HEAD"):
                p = m.path / rel
                try:
                    st = p.stat()
                    h.append((name + "/" + rel, st.st_mtime_ns, st.st_size))
                except OSError:
                    continue
        return str(hash(tuple(h)))


def token_env(token: str) -> dict:
    """Environment for git operations that need authentication.

    The token is injected through the environment only — never on the command
    line, never in .git/config, never written anywhere by Agency OS.
    """
    if not token:
        return {}
    askpass = Path(os.environ.get("AGENCY_OS_HOME", Path.home() / ".agency-os")) / "run" / "askpass.sh"
    try:
        askpass.parent.mkdir(parents=True, exist_ok=True)
        askpass.write_text('#!/bin/sh\ncase "$1" in\n  Username*) echo x-access-token ;;\n  *) echo "$AGENCY_OS_GIT_TOKEN" ;;\nesac\n',
                           encoding="utf-8")
        askpass.chmod(0o700)
    except OSError:
        return {}
    return {
        "GIT_ASKPASS": str(askpass),
        "AGENCY_OS_GIT_TOKEN": token,
        "GIT_TERMINAL_PROMPT": "0",
    }
