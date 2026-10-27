"""Small, patient GitHub API client.

Anonymous GitHub allows 60 requests/hour.  The deck therefore treats the API as
an *optional enrichment*: results are cached on disk, refreshed only on demand
or after a TTL, and every failure degrades to the last good copy with an honest
`stale` flag.  With a token the limit is 5 000/h and private repositories work.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UA = "agency-os/1.0 (+https://github.com/dreamer2664/agency-os)"


class GitHub:
    def __init__(self, user: str, cache_dir: Path, token: str = "", ttl: int = 600, logger=None):
        self.user = user
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.ttl = ttl
        self.log = logger or (lambda *a, **k: None)
        self.mem: dict[str, tuple[float, object]] = {}
        self.rate = {"limit": None, "remaining": None, "reset": None}

    # ------------------------------------------------------------------ core
    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "User-Agent": UA,
             "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")

    def get(self, path: str, ttl: int | None = None, allow_stale: bool = True):
        ttl = self.ttl if ttl is None else ttl
        url = path if path.startswith("http") else API + path
        hit = self.mem.get(url)
        if hit and time.time() - hit[0] < ttl:
            return hit[1], {"cached": True, "stale": False}
        cp = self._cache_path(url)
        disk = None
        if cp.exists():
            try:
                disk = json.loads(cp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                disk = None
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self._note_rate(resp.headers)
            cp.write_text(json.dumps({"ts": time.time(), "body": body}), encoding="utf-8")
            self.mem[url] = (time.time(), body)
            return body, {"cached": False, "stale": False}
        except urllib.error.HTTPError as exc:
            self._note_rate(exc.headers)
            msg = ""
            try:
                msg = json.loads(exc.read().decode("utf-8")).get("message", "")
            except Exception:
                pass
            if allow_stale and disk:
                return disk["body"], {"cached": True, "stale": True,
                                      "error": f"HTTP {exc.code}: {msg}".strip()}
            return None, {"cached": False, "stale": True, "error": f"HTTP {exc.code}: {msg}".strip()}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if allow_stale and disk:
                return disk["body"], {"cached": True, "stale": True,
                                      "error": f"{exc.__class__.__name__}: {exc}"}
            return None, {"cached": False, "stale": True, "error": f"{exc.__class__.__name__}: {exc}"}

    def _note_rate(self, headers) -> None:
        if not headers:
            return
        try:
            self.rate = {"limit": int(headers.get("X-RateLimit-Limit", 0) or 0),
                         "remaining": int(headers.get("X-RateLimit-Remaining", 0) or 0),
                         "reset": int(headers.get("X-RateLimit-Reset", 0) or 0)}
        except (TypeError, ValueError):
            pass

    # ------------------------------------------------------------- endpoints
    def repos(self, limit: int = 100) -> tuple[list, dict]:
        body, meta = self.get(f"/users/{self.user}/repos?per_page={limit}&sort=updated", ttl=1800)
        if not isinstance(body, list):
            return [], meta
        rows = [{
            "name": r.get("name"), "slug": r.get("full_name"),
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "updated_at": r.get("updated_at") or "",
            "pushed_at": r.get("pushed_at") or "",
            "size_kb": r.get("size") or 0,
            "stars": r.get("stargazers_count") or 0,
            "fork": bool(r.get("fork")),
            "archived": bool(r.get("archived")),
            "default_branch": r.get("default_branch") or "main",
            "url": r.get("html_url") or "",
        } for r in body]
        rows.sort(key=lambda r: r["pushed_at"] or "", reverse=True)
        return rows, meta

    def commits(self, slug: str, limit: int = 20, ttl: int = 600) -> tuple[list, dict]:
        body, meta = self.get(f"/repos/{slug}/commits?per_page={min(limit, 50)}", ttl=ttl)
        if not isinstance(body, list):
            return [], meta
        rows = []
        for c in body:
            commit = c.get("commit") or {}
            author = commit.get("author") or {}
            rows.append({
                "sha": (c.get("sha") or "")[:10],
                "message": (commit.get("message") or "").splitlines()[0][:200],
                "author": author.get("name") or (c.get("author") or {}).get("login") or "",
                "date": author.get("date") or "",
                "url": c.get("html_url") or "",
            })
        return rows, meta

    def pulls(self, slug: str, state: str = "open", limit: int = 30) -> tuple[list, dict]:
        body, meta = self.get(f"/repos/{slug}/pulls?state={state}&per_page={min(limit, 50)}", ttl=600)
        if not isinstance(body, list):
            return [], meta
        rows = [{
            "number": p.get("number"),
            "title": p.get("title") or "",
            "user": (p.get("user") or {}).get("login") or "",
            "created_at": p.get("created_at") or "",
            "updated_at": p.get("updated_at") or "",
            "draft": bool(p.get("draft")),
            "branch": (p.get("head") or {}).get("ref") or "",
            "url": p.get("html_url") or "",
        } for p in body]
        return rows, meta

    def overview(self, core: list[str]) -> dict:
        repos, rmeta = self.repos()
        out = {"repos": repos, "meta": rmeta, "commits": {}, "pulls": {},
               "rate": self.rate, "authenticated": bool(self.token)}
        for slug in core:
            commits, cm = self.commits(slug, limit=8)
            pulls, pm = self.pulls(slug)
            out["commits"][slug] = {"rows": commits, "meta": cm}
            out["pulls"][slug] = {"rows": pulls, "meta": pm}
        return out
