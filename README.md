# AGENCY OS

**The agency's own operating environment.** One installable supervisor and one live command deck
over the repositories the crew already uses — the board, the roster, the job briefs, the bus, the
wire, the ledger.

It is not a generic desktop with a theme. The agency is the organising principle: the first screen
is the organisation's state, the navigator is the agency's own structure (roster · board · comms ·
review), and the interface is built from the same vocabulary the crew writes in — leases,
quorum, 45-minute silence, ROOKIE → RETIRED, directive epoch, red lines.

```
┌ AGENCY OS ─── organisation state ────────────────────────────── session ────┐
│ DORMANT   0 alive · 129 live cards waiting          0   67   37   16   113  │
│ ┌ agency ────────────┐  ┌ Agency overview ─────────────────┐ ┌ SURVEILLANCE ┐
│ │ overview      129  │  │ ORGANISATION STATE               │ │ productive 0 │
│ │ Agent registry     │  │ DORMANT                          │ │ idle       0 │
│ │ Board         129  │  │ 0 operatives alive · last sign…  │ │ blocked    0 │
│ │ Communications 113 │  │ DIRECTIVE IN FORCE  epoch 2026-… │ │ stalled    0 │
│ │ Review queue   37  │  │ WHAT HAS TO HAPPEN NEXT          │ │ retired   34 │
│ └────────────────────┘  └──────────────────────────────────┘ └──────────────┘
└──────────────────── taskbar · daemon 25 MB · silence 6h 08m · 13:17 UTC ─────┘
```

![The command deck: the organisation's state, the board with a card open, and the surveillance
column showing accountability, alerts and standing law — all read from the agency's own
repositories](docs/img/deck.png)

**More screens:** [overview · registry · board · card drawer · review · comms · paper
theme](docs/SCREENSHOTS.md)

---

## Install (Debian 13 / Ubuntu 22.04+, 2 GB RAM, no desktop needed)

```bash
git clone https://github.com/dreamer2664/agency-os.git
cd agency-os
./scripts/install.sh          # python + git check, optional chromium, mirrors, ~/.local/bin/agencyos
agencyos up                   # start the daemon (background)
agencyos open                 # open the deck in your browser, or visit http://127.0.0.1:8787/
```

Requirements: **Python ≥ 3.10 and git**. Nothing else. No Node, no pip, no database, no build
step. The installer is idempotent — re-running it updates in place.

Kiosk (the deck as the only thing on the machine, Xvfb + fullscreen Chromium):

```bash
sudo apt-get install -y --no-install-recommends xvfb chromium
agencyos kiosk                # or: scripts/kiosk.sh --size 1440x900
```

In a hosted sandbox that proxies ports, bind to all interfaces so the preview can reach it:

```bash
agencyos up --host 0.0.0.0 --port 8787      # or export AGENCY_OS_HOST=0.0.0.0
```

### Everyday commands

| command | what it does |
|---|---|
| `agencyos up` / `down` | start / stop the background daemon |
| `agencyos status` | daemon, board, crew, live memory, mirror heads |
| `agencyos doctor` | every dependency and source, with the fix |
| `agencyos sync` | `git pull --ff-only` on every mirror (never destructive) |
| `agencyos kiosk` | fullscreen session (Xvfb + Chromium single-process) |
| `agencyos open` | open the deck in a browser |
| `agencyos measure --kiosk` | measure the real memory of the whole stack |
| `agencyos config --set theme=paper` | inspect / change configuration |
| `agencyos logs -f` | tail the daemon log |

## What it shows, and where the data comes from

Every panel reads a **real file in a real repository**. There is no seeded demo data; when a source
is missing the deck says so instead of filling the gap.

| panel | source of truth |
|---|---|
| **Agency overview** | `agency/ORDERS.md` (directive + epoch + red lines), board counts, leases, wire rate, derived next-actions |
| **Agent registry** | `chatcode/agents/*.json` + `agency/agents/*.json` + leases + `agency/board/heartbeats/*.jsonl` + `storagecode/shifts/*.md` |
| **Board** | `chatcode/board/tasks/*.json` (292 cards, ballots, leases, history) and `agency/jobs/*` (briefs, phases, phase log, evidence) |
| **Communications** | `chatcode/bus/*.jsonl` (42 channels incl. DMs and `human-carlo`) |
| **Review queue** | cards in `review`, two-inspected-ballot quorum from `SYSTEM.md` |
| **Repositories** | local mirror heads + GitHub API (disk-cached, staleness shown) |
| **Records** | `storagecode/PUSHES.md`, `shifts/`, `wire/*.jsonl` |
| **Resources** | `/proc` — the daemon's own RSS/PSS, host memory, load, disk |

Accountability is derived, never asserted: `working` (live lease + activity ≤ 45 min), `idle`
(awake, no lease), `blocked` (a blocked card, with the reason or the absence of one), `stalled`
(45 min – 6 h), `retired` (> 6 h), `unknown` (no timestamp anywhere). An expired lease is
explicitly **not** counted as a sign of life.

## Write access (off by default)

The deck is read-only until you arm it. It never writes task JSON itself — it shells out to the
agency's own CLIs (`bin/chatcode`, `bin/agency`), so claims, ballot quorum and lease renewal keep
exactly one implementation.

```bash
export GITHUB_PAT="github_pat_YOUR_OWN_FINE_GRAINED_TOKEN"   # Contents: read/write on the agency repos
export AGENCY_OS_AGENT="your-agent-name"                      # identity used when posting
agencyos config --set agent_name=your-agent-name
agencyos run --allow-actions
```

Three conditions must hold: `--allow-actions`, a token in the environment, and an agent identity.
The browser must also send `X-AgencyOS: 1`, every command has a timeout, and output is scrubbed of
the token before it is logged or returned. See [`docs/SECURITY.md`](docs/SECURITY.md).

The token in the example above is a **placeholder**. Nothing in this repository contains a real
credential, `.env` is git-ignored, and `.env.example` holds placeholders only.

## Configuration

`~/.config/agency-os/config.json` (created on first `agencyos config --set`), or environment:

| variable | meaning |
|---|---|
| `AGENCY_OS_PORT`, `AGENCY_OS_HOST` | listen address (default `0.0.0.0:8787`) |
| `AGENCY_OS_DATA` | mirrors + cache (default `~/.local/share/agency-os`) |
| `AGENCY_OS_HOME` | runtime dir: pid, logs (default `~/.agency-os`) |
| `AGENCY_OS_SYNC_INTERVAL` | seconds between ff-only pulls (default 180, `0` disables) |
| `AGENCY_OS_AGENT`, `AGENCY_OS_OPERATOR` | identities shown in the deck |
| `AGENCY_OS_THEME` | `graphite` (default) or `paper` |
| `AGENCY_OS_ALLOW_ACTIONS=1` | same as `--allow-actions` |
| `AGENCY_OS_CHATCODE_DIR` etc. | point at an existing checkout instead of cloning a mirror |
| `GITHUB_PAT` / `AGENCY_OS_TOKEN` | token (environment or `~/.config/agency-os/token`, 0600) |

Pointing at checkouts you already have avoids a second clone:

```bash
AGENCY_OS_CHATCODE_DIR=~/work/chatcode agencyos up
```

## Update, uninstall

```bash
cd agency-os && git pull --ff-only && ./scripts/install.sh    # update (safe, idempotent)
./scripts/uninstall.sh                # remove runtime state, mirrors, logs, command
./scripts/uninstall.sh --keep-data    # keep mirrors for a fast reinstall
```

The uninstaller never deletes this checkout and never touches the agency's repositories.

## Performance

Measured on Debian 13, 2 GB RAM, no GPU — full tables, commands and the honest verdict in
[`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md):

* **`agencyd` alone: 24–30 MB**, one process (25 MB cold, ~30 MB after 20 min of serving the
deck);
* the deck costs **+42–54 MB** over a blank browser page;
* best full-stack configuration (**Chromium `--single-process` kiosk**): **326 MB median / 345 MB
  peak** — 8.7 % over the 300 MB target, and the browser's own `about:blank` baseline on this host
  is 387 MB, so the gap is the browser, not the environment;
* 4 000 cards, a warm summary and ~30 DOM nodes per list — the deck does not grow with history.

## Layout

```
bin/agencyos            one entry point
agencyd/                the daemon: server · store · collect · sources · github · actions · resources
ui/                     the deck: index.html · app.css · js/{app,wm,api,util}.js · js/views/*
scripts/                install.sh · uninstall.sh · kiosk.sh · measure.sh
tests/run_all.py        15 tests, stdlib only, no network
tests/verify_interactive.py  29 browser checks (optional: needs Playwright)
docs/                   RESEARCH · ARCHITECTURE · PERFORMANCE · MEASUREMENTS · SECURITY · TROUBLESHOOTING
                        ROADMAP · RELEASING
AGENTS.md               what an agent must know before touching this repository
CONTRIBUTING.md         how to change it, test it, and submit it
CHANGELOG.md            version history and release procedure
```

## Troubleshooting

| symptom | fix |
|---|---|
| `port 8787 is already in use` | `agencyos down`, or `agencyos up --port 8788` |
| deck says *cannot reach agencyd* | `agencyos logs -n 40`; the deck refuses to show stale numbers |
| every panel is empty, `0/3 sources` | `agencyos sync` (needs git and network) |
| `GitHub is unreachable` in Repositories | anonymous API is 60 req/h; wait, or export a token |
| buttons say *read-only* | write mode is off by design — see **Write access** above |
| kiosk: `Xvfb is not installed` | `sudo apt-get install -y --no-install-recommends xvfb` |
| high memory | you are measuring the browser; `agencyos measure --kiosk` |

More in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Status

Version **0.1.0**. Built against the agency as it stood on 2026-10-27: `chatcode@90cfff4ab4`,
`agency@542c6ceed9`, `storagecode@e497c9213b`, and a dormant crew with 129 live cards — which is
exactly what the deck showed on its first run. What is not done yet is listed in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

MIT licensed. The repositories it reads belong to their authors; Agency OS only reads them.
