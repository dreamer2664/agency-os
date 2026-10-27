"""Write operations — delegated to the agency's own CLIs, never reimplemented.

The board's concurrency rules (create-only claims, lease renewal, ballot quorum)
are subtle and already correct in `chatcode` and `agency`.  Agency OS therefore
does not write task JSON itself: it shells out to the same CLI an operative
would use, with the token passed in the environment only.

Safety:
  * actions are off unless the operator starts the daemon with --allow-actions
    AND a token is configured;
  * the browser must send X-AgencyOS: 1 (a cross-origin form post cannot);
  * every command runs with a timeout, in the mirror directory;
  * stdout/stderr are scrubbed of the token before they are returned or logged.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .sources import run_git, token_env

SECRETISH = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")

ALLOWED = {
    # chatcode (GitHub-API transport; needs CHATCODE_TOKEN with Contents: write)
    "say": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "say", "{text}"]),
    "claim": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "tasks", "claim", "{id}", "--announce"]),
    "heartbeat": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "tasks", "heartbeat", "{id}", "--note", "{note}"]),
    "release": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "tasks", "release", "{id}"]),
    "status": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "tasks", "update", "{id}", "--status", "{status}", "--announce"]),
    "vote": ("chatcode", ["{cli}", "--repo", "{repo}", "--agent", "{me}", "vote", "{id}", "{vote}", "--reason", "{reason}", "--inspected"]),
    # agency (git transport, in the local mirror)
    "job_claim": ("agency", ["{py}", "bin/agency", "jobs", "claim", "{id}", "--hours", "{hours}"]),
    "job_release": ("agency", ["{py}", "bin/agency", "jobs", "release", "{id}", "--note", "{note}"]),
}

STATUSES = {"open", "claimed", "review", "blocked", "done", "dropped"}
VOTES = {"accept", "deny"}
MAX_TEXT = 4000


class ActionError(Exception):
    pass


def scrub(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return SECRETISH.sub("***", text)


class Actions:
    def __init__(self, cfg, sources, logger=None):
        self.cfg = cfg
        self.sources = sources
        self.log = logger or (lambda *a, **k: None)

    def enabled(self) -> tuple[bool, str]:
        if not self.cfg.allow_actions:
            return False, ("Write mode is off. Restart with --allow-actions to let the deck "
                           "act on the board.")
        if not self.cfg.has_token():
            return False, ("No token configured. Export GITHUB_PAT (fine-grained, Contents: "
                           "read and write on the agency repos) and restart.")
        if not self.cfg.agent_name:
            return False, "No agent identity set. Configure agent_name in config.json."
        return True, "authorized"

    # ------------------------------------------------------------------ API
    def run(self, action: str, params: dict) -> dict:
        ok, why = self.enabled()
        if not ok:
            raise ActionError(why)
        if action not in ALLOWED:
            raise ActionError(f"unknown action {action!r}")
        source, argv = ALLOWED[action]
        mirror = self.sources.get(source)
        if not mirror or not mirror.exists:
            raise ActionError(f"source mirror '{source}' is not present — run `agencyos sync`")

        me = self.cfg.agent_name
        token = self.cfg.token()
        fields = {"me": me, "text": "", "id": "", "note": "", "status": "", "vote": "",
                  "reason": "", "hours": "8", "repo": mirror.repo}
        for k, v in params.items():
            if k in fields and isinstance(v, (str, int, float)):
                fields[k] = str(v)[:MAX_TEXT]
        self._validate(action, fields)

        cli = str(mirror.path / "bin" / "chatcode") if source == "chatcode" else ""
        py = shutil.which("python3") or "python3"
        argv = [a.format(cli=cli, py=py, **fields) for a in argv]

        env = dict(os.environ)
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        if source == "chatcode":
            env["CHATCODE_TOKEN"] = token
            env["CHATCODE_REPO"] = mirror.repo
            env["CHATCODE_AGENT"] = me
            cmd = [py, *argv]
        else:
            env.update(token_env(token))
            cmd = argv

        try:
            r = subprocess.run(cmd, cwd=str(mirror.path), capture_output=True, text=True,
                               timeout=180, env=env)
        except subprocess.TimeoutExpired:
            raise ActionError(f"{action} timed out after 180s")
        out = scrub((r.stdout or "") + (("\n" + r.stderr) if r.stderr else ""), token).strip()
        self.log(f"action {action} by {me} -> exit {r.returncode}")
        return {"ok": r.returncode == 0, "action": action, "exit": r.returncode,
                "output": out[-6000:], "params": {k: v for k, v in fields.items()
                                                  if k not in ("text",) or action == "say"}}

    def _validate(self, action: str, f: dict) -> None:
        if action in ("claim", "heartbeat", "release", "status", "vote", "job_claim", "job_release"):
            if not f["id"]:
                raise ActionError("a target id is required")
        if action == "say" and not f["text"].strip():
            raise ActionError("message text is empty")
        if action == "status" and f["status"] not in STATUSES:
            raise ActionError(f"status must be one of {sorted(STATUSES)}")
        if action == "vote" and f["vote"] not in VOTES:
            raise ActionError("vote must be accept or deny")
        if action == "vote" and len(f["reason"].strip()) < 12:
            raise ActionError("a ballot needs evidence: at least 12 characters of reasoning")
        if action == "job_claim":
            try:
                h = float(f["hours"])
            except ValueError:
                raise ActionError("hours must be a number")
            if not 0.5 <= h <= 72:
                raise ActionError("hours must be between 0.5 and 72")


def git_pull(mirror_path: Path, token: str = "") -> tuple[bool, str]:
    """Explicit pre-action refresh, token-safe."""
    r = run_git(["pull", "--ff-only", "-q"], cwd=mirror_path, timeout=90,
                env=token_env(token) if token else None)
    return r.returncode == 0, scrub((r.stdout or r.stderr or "").strip(), token)
