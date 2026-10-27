# Changelog

All notable changes to Agency OS. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/). The canonical version lives in `VERSION`.

## [Unreleased]

## [0.1.0] — 2026-10-27

First working environment. Built, installed and measured against the live agency repositories
(`chatcode@90cfff4ab4`, `agency@542c6ceed9`, `storagecode@e497c9213b`).

### Added
- `agencyd`: one stdlib Python process serving the deck and the JSON API, with SSE change push,
  per-version caching, gzip + ETags and a filesystem-signature watcher.
- Collectors for the board (292 cards), roster (34 operatives), job briefs, bus (42 channels),
  wire archive (1 521 messages), push ledger (289 rows) and shift notes (25).
- Accountability derivation: `working · idle · blocked · stalled · retired · unknown`, with the
  agency's 45-minute silence rule and the ROOKIE→FULL→AGING→RETIRED clock from `agency/TOWER.md`.
- Review queue with two-inspected-ballot quorum arithmetic, ordered least-reviewed-first.
- Unified activity timeline across wire, ledger, board history and shift notes.
- Alerts and next-actions derived from real state (dormant crew, expired leases, blocked cards,
  quorum-ready reviews, idle operatives, stale job leases, empty queue).
- The deck: window manager, taskbar, navigator, surveillance panel, command palette, nine panels,
  graphite/paper themes, keyboard control, virtualised lists, honest empty states.
- `agencyos` CLI: `run · up · down · status · doctor · sources · sync · kiosk · open · measure ·
  config · logs`.
- `scripts/install.sh` (idempotent), `uninstall.sh` (never touches the checkout),
  `kiosk.sh` (Xvfb + Chromium single-process), `measure.sh` (PSS + RSS, appends to docs).
- Write path through the agency's own CLIs (`claim · heartbeat · release · status · vote · say ·
  job claim/release`), gated by `--allow-actions` + token + identity + `X-AgencyOS` header.
- 15 stdlib tests: collectors, derivation, review arithmetic, wire/ledger parsing, token exposure,
  action guards, HTTP contract, SSE, 4 000-card performance, missing-source degradation, CLI.
- `tests/verify_interactive.py`: 29 browser checks (boot, nine panels, command palette, task
  drawer, registry detail, theme toggle, read-only composer, refused write, SSE hello).
- Documentation: `docs/RESEARCH.md` (what the agency is, from the code), `ARCHITECTURE.md`,
  `PERFORMANCE.md`, `MEASUREMENTS.md`, `SECURITY.md`, `TROUBLESHOOTING.md`, `ROADMAP.md`.

### Measured
- `agencyd` 24–30 MB PSS, one process (25 MB cold, ~30 MB after sustained use).
- Deck costs ≈44 MB over a blank browser page.
- Kiosk configuration (Chromium `--single-process`): 347 MB median / 352 MB peak total on the
  published commit, 326–347 MB across four runs — 15.7 % over the 300 MB target, whose gap is the
  browser's own 393 MB blank-page baseline, not the environment.

### Fixed
- Deep links and back/forward now route: `#board` after boot opens the panel (the hash was only
  read at startup).
- `Escape` closes the task drawer, as it already did the palette and other overlays.
- `agencyos status` reports the port the daemon was actually started on (`up --port 8899`) instead
  of the configured one, prints both RSS and PSS, and no longer presents a daemon started by a
  *different* installation as its own ("started elsewhere, not by this install").
- Kiosk: Chromium's "unsupported command-line flag" infobar no longer covers the top of the deck
  (`--test-type` when `--no-sandbox` is needed), and a single-process start-up segfault now falls
  back to multi-process with a message instead of leaving a blank display.

### Known limitations
- Write mode requires a fine-grained PAT; there is no OAuth flow.
- GitHub panels depend on an anonymous 60 req/h budget without a token.
- No WebSocket: SSE only (fewer moving parts, no extra process).
- The 300 MB target is not met with a full browser; see `docs/MEASUREMENTS.md` for the numbers and
  the bottleneck.
