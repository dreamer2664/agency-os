"""Agency OS configuration.

Resolution order: explicit argument > environment > config file > default.
No secret is ever written to a file by this module.  Tokens are read from the
environment (or from a 0600 token file the operator creates themselves) and are
never included in API responses, logs, or the process argument list.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP = "agency-os"
VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def _version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


VERSION = _version()

HOME = Path(os.environ.get("AGENCY_OS_HOME", Path.home() / ".agency-os"))
CONFIG_PATH = Path(os.environ.get("AGENCY_OS_CONFIG", Path.home() / ".config" / "agency-os" / "config.json"))
TOKEN_FILE = Path(os.environ.get("AGENCY_OS_TOKEN_FILE", Path.home() / ".config" / "agency-os" / "token"))

DEFAULT_SOURCES = [
    # name        repo slug                      sparse paths (keeps the mirror small)
    ("chatcode", "dreamer2664/chatcode",
     ["/board/", "/agents/", "/bus/", "/memory/", "/bin/", "/dashboard/",
      "/STATUS.md", "/SYSTEM.md", "/PROTOCOL.md", "/START_HERE.md", "/WORKER.md"]),
    ("agency", "dreamer2664/agency",
     ["/agents/", "/board/", "/jobs/", "/ledger/", "/bin/", "/*.md"]),
    ("storagecode", "dreamer2664/storagecode",
     ["/wire/", "/shifts/", "/data/", "/tools/", "/*.md"]),
]


@dataclass
class SourceConfig:
    name: str
    repo: str
    sparse: list = field(default_factory=list)
    path: str = ""
    enabled: bool = True


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8787
    data_dir: str = str(Path.home() / ".local" / "share" / "agency-os")
    home: str = str(HOME)
    sources: list = field(default_factory=list)
    sync_interval: int = 180          # seconds; 0 disables background sync
    sync_on_start: bool = True
    watch_interval: float = 4.0       # seconds between filesystem signature checks
    allow_actions: bool = False       # writes are opt-in AND require a token
    operator: str = "carlo"           # the human identity shown in the deck
    agent_name: str = ""              # identity used when posting as an agent
    theme: str = "graphite"
    gh_cache_ttl: int = 600           # seconds for GitHub API responses
    activity_limit: int = 600
    log_max_bytes: int = 2 * 1024 * 1024

    # -- secrets live only in memory -------------------------------------
    _token: str = ""

    def token(self) -> str:
        if self._token:
            return self._token
        for var in ("AGENCY_OS_TOKEN", "GITHUB_PAT", "CHATCODE_TOKEN", "GITHUB_TOKEN"):
            val = os.environ.get(var, "").strip()
            if val:
                self._token = val
                return val
        try:
            if TOKEN_FILE.exists():
                val = TOKEN_FILE.read_text(encoding="utf-8").strip()
                if val:
                    self._token = val
                    return val
        except OSError:
            pass
        return ""

    def has_token(self) -> bool:
        return bool(self.token())

    def source_dir(self, name: str) -> Path:
        for s in self.sources:
            if s.name == name:
                return Path(s.path) if s.path else Path(self.data_dir) / "src" / name
        return Path(self.data_dir) / "src" / name

    def to_public_dict(self) -> dict:
        """Config as safe to send to a browser: booleans, never the token."""
        return {
            "version": VERSION,
            "host": self.host,
            "port": self.port,
            "operator": self.operator,
            "agent_name": self.agent_name,
            "theme": self.theme,
            "actions_enabled": bool(self.allow_actions and self.has_token()),
            "actions_requested": bool(self.allow_actions),
            "authenticated": self.has_token(),
            "data_dir": self.data_dir,
            "sync_interval": self.sync_interval,
        }


def default_config() -> Config:
    cfg = Config()
    cfg.sources = [SourceConfig(name=n, repo=r, sparse=list(p)) for n, r, p in DEFAULT_SOURCES]
    return cfg


def load_config(path: str | None = None) -> Config:
    cfg = default_config()
    p = Path(path) if path else CONFIG_PATH
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for key in ("host", "port", "data_dir", "home", "sync_interval", "sync_on_start",
                    "watch_interval", "allow_actions", "operator", "agent_name", "theme",
                    "gh_cache_ttl", "activity_limit", "log_max_bytes"):
            if key in raw and raw[key] is not None:
                setattr(cfg, key, type(getattr(cfg, key))(raw[key]))
        if isinstance(raw.get("sources"), list) and raw["sources"]:
            cfg.sources = []
            for s in raw["sources"]:
                cfg.sources.append(SourceConfig(
                    name=s.get("name", "?"),
                    repo=s.get("repo", ""),
                    sparse=list(s.get("sparse", [])),
                    path=s.get("path", ""),
                    enabled=bool(s.get("enabled", True)),
                ))
    # environment overrides
    env_map = {
        "AGENCY_OS_HOST": "host",
        "AGENCY_OS_PORT": "port",
        "AGENCY_OS_DATA": "data_dir",
        "AGENCY_OS_SYNC_INTERVAL": "sync_interval",
        "AGENCY_OS_OPERATOR": "operator",
        "AGENCY_OS_AGENT": "agent_name",
        "AGENCY_OS_THEME": "theme",
    }
    for env, attr in env_map.items():
        if env in os.environ and os.environ[env] != "":
            cur = getattr(cfg, attr)
            try:
                setattr(cfg, attr, type(cur)(os.environ[env]))
            except (TypeError, ValueError):
                pass
    if os.environ.get("AGENCY_OS_ALLOW_ACTIONS", "").lower() in ("1", "true", "yes"):
        cfg.allow_actions = True
    # an explicitly configured source path in the environment wins
    for name in ("chatcode", "agency", "storagecode"):
        env = os.environ.get(f"AGENCY_OS_{name.upper()}_DIR")
        if env:
            for s in cfg.sources:
                if s.name == name:
                    s.path = env
    return cfg


def save_config(cfg: Config, path: str | None = None) -> Path:
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "host": cfg.host,
        "port": cfg.port,
        "data_dir": cfg.data_dir,
        "sync_interval": cfg.sync_interval,
        "sync_on_start": cfg.sync_on_start,
        "allow_actions": cfg.allow_actions,
        "operator": cfg.operator,
        "agent_name": cfg.agent_name,
        "theme": cfg.theme,
        "sources": [asdict(s) for s in cfg.sources],
    }
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def ensure_dirs(cfg: Config) -> None:
    for d in (Path(cfg.home), Path(cfg.home) / "log", Path(cfg.home) / "run",
              Path(cfg.data_dir), Path(cfg.data_dir) / "src", Path(cfg.data_dir) / "cache"):
        d.mkdir(parents=True, exist_ok=True)
