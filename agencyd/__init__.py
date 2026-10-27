"""agencyd — the Agency OS daemon.

One process, stdlib only. Reads the agency's git mirrors, derives one snapshot,
serves the deck and a JSON API over it, and — only when explicitly armed —
delegates writes to the agency's own CLIs.

Read docs/ARCHITECTURE.md before changing a module here.
"""

__all__ = ["config", "sources", "collect", "store", "server", "actions", "github", "resources"]
