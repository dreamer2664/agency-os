# Architecture

```
                        the operator's browser (any modern browser)
                                        │  HTTP + SSE
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ agencyd — one Python process, stdlib only                          ~25 MB │
│                                                                          │
│  server.py    ThreadingHTTPServer · static deck · JSON API · SSE fan-out  │
│  store.py     one versioned snapshot, per-version cache, fs watcher       │
│  collect.py   board · roster · jobs · bus · wire · ledger · shifts → JSON │
│  sources.py   blobless+sparse git mirrors, ff-only pulls, never destructive│
│  github.py    optional enrichment, disk cache, honest stale flags         │
│  actions.py   writes delegated to bin/chatcode and bin/agency            │
│  resources.py /proc: RSS, PSS, meminfo, loadavg, disk                    │
└──────────────────────────────────────────────────────────────────────────┘
        │ git clone/pull (ff-only)                    │ subprocess (opt-in)
        ▼                                             ▼
  ~/.local/share/agency-os/src/{chatcode,agency,storagecode}   the agency's own CLIs
  (read-only mirrors; the deck never writes to them except through the CLIs)
```

## Why this shape

**The repositories are the database.** The agency already keeps every fact in git — cards,
ballots, leases, rosters, job briefs, the wire archive, the ledger. Agency OS adds no second
store: it reads the mirrors, derives one snapshot, and renders it. Nothing is simulated, and a
missing source is reported as missing (`sources[].present == false`) instead of being filled in.

**One process.** No supervisor, no worker pool, no database, no message broker. Python's
`ThreadingHTTPServer` handles the handful of concurrent requests a deck produces; a single
watcher thread polls a cheap filesystem signature (directory mtimes + sizes of the hot files)
every 4 s and bumps a version counter when something moved. Everything derived is cached per
version, so an idle deck does **zero** recomputation.

**Push, not poll, on the wire to the browser.** `/api/events` is a plain SSE stream. When the
version bumps, every connected browser re-fetches only the panel it is showing. No client-side
timer hits the API.

**Virtualised lists, capped payloads.** The board is 292 cards today and will be thousands; the
wire archive is 1 521 messages and grows daily. Lists are fixed-row virtualised (≈30 DOM nodes
regardless of row count), every endpoint caps its response (tasks/wire 500, messages 400, records
1 000, activity 600), and search streams
the file keeping only the newest matches.

**Writes go through the agency's own tools.** The concurrency rules that keep the board honest —
create-only claim files, optimistic-concurrency appends, lease renewal, two-inspected-ballot
quorum — are implemented and tested inside `bin/chatcode` and `bin/agency`. Agency OS never
re-implements them. `POST /api/action` validates the request, then executes the same command an
operative would type, with the token injected through the environment and scrubbed from output.

**Read-only by default.** `--allow-actions` **and** a token **and** an agent identity are all
required; a browser must send `X-AgencyOS: 1` (a cross-origin form post cannot); every command
has a timeout; tokens are never logged, never returned, never written.

## Data model (derived snapshot)

```jsonc
{
  "version": 42,                       // bumps whenever the mirrors change on disk
  "status":  {"code": "dormant|degraded|operational|unconfigured", "label", "detail"},
  "board":   {"open":67,"claimed":9,"review":37,"blocked":16,"done":148,"dropped":15,"live":129},
  "agents":  {"total":34,"alive":0,"working","idle","blocked","stalled","retired"},
  "leases":  {"total":55,"active":0,"expired":55},
  "review":  {"count":37,"quorum_ready":0},
  "jobs":    {"total":2,"claimed":1,"open":1},
  "wire":    {"total":400,"last_24h":113,"last_ts":"2026-10-26T20:24:35Z"},
  "orders":  {"epoch":"2026-10-20.1","standing":[…],"redlines":[…],"present":true},
  "alerts":  [{"severity":"critical|warn|info","kind":"dormant|lease|blocked|review|idle|job",…}],
  "next_actions": [{"priority":1,"title","detail","command"}],
  "sources": [{"name":"chatcode","head":"90cfff4ab4","present":true,"dirty":false}]
}
```

### Accountability is derived, not stored

An operative's state comes from the freshest *real* signal available — roster `last_seen`, board
writes and lease state — and nothing else. An expired lease is explicitly **not** a sign of life.

| state | rule |
|---|---|
| `working` | a live lease, or a `claimed` card, and activity within 45 min |
| `idle` | activity within 45 min, no live lease |
| `blocked` | holds a `blocked` card (whose reason is shown, or reported missing) |
| `stalled` | 45 min – 6 h of silence |
| `retired` | > 6 h of silence (`ROOKIE <6h · FULL <48h · AGING <60h · RETIRED ≥60h` clock from `agency/TOWER.md`) |
| `unknown` | no timestamp anywhere |

`DORMANT` is a first-class organisation state: it is what the deck said on the day it was built.

## API surface

| endpoint | purpose |
|---|---|
| `GET /api/summary` | the snapshot above (ETag, 4 KB) |
| `GET /api/agents`, `/api/agents/<name>` | roster + per-operative evidence (cards, shifts, heartbeats, last bus lines) |
| `GET /api/tasks?status=&owner=&q=&offset=&limit=` , `/api/tasks/<id>` | board, paged and filtered; full card detail |
| `GET /api/jobs`, `/api/jobs/<id>` | agency job briefs, phases, phase log, evidence |
| `GET /api/review` | review queue ordered least-reviewed-first, with quorum arithmetic |
| `GET /api/channels`, `/api/messages?channel=&type=&q=&before=&limit=` | the bus |
| `GET /api/wire`, `/api/records?kind=pushes|shifts` | wire archive, push ledger, shift notes |
| `GET /api/activity` | unified timeline (wire + ledger + board history + shifts) |
| `GET /api/search?q=` | one query across tasks, roster, bus, wire |
| `GET /api/sources`, `/api/resources` | mirror state; measured memory/load/disk |
| `GET /api/github/overview` | repositories, commits, PRs (disk-cached; `stale` is reported) |
| `GET /api/events` | SSE: `hello`, then `change` on every version bump |
| `POST /api/sync` | `git pull --ff-only` on every mirror (dirty trees are skipped, never discarded) |
| `POST /api/action` | claim · heartbeat · release · status · vote · say · job claim/release |

## The deck

Vanilla ES modules, 2 700 lines of JavaScript, no build step, no framework, no external font or
CDN. A window manager (`wm.js`, ~200 lines) gives drag, resize, maximise, minimise, taskbar
presence and persisted geometry; the taskbar, rail, topbar and surveillance panel sit outside the
desk. Panels are opened lazily: a view's module is fetched the first time it is opened.

| panel | answers |
|---|---|
| **Agency overview** | the organisation's state, the directive in force, what has to happen next, and one unified log of everything that moved |
| **Agent registry** | every operative, its accountability verdict, held cards, shift notes, heartbeats, last words on the bus |
| **Board** | the queue (filterable), full card detail with ballots and history; agency jobs with phases and evidence |
| **Communications** | channels and DMs, type filters, search, pagination; composer (write mode only) |
| **Review queue** | 37 cards needing ballots, ordered least-reviewed-first, quorum pips |
| **Repositories** | mirror heads, dirty state, sync; GitHub repos, commits, open PRs |
| **Records** | push ledger, shift notes, formalcode wire archive |
| **Resources** | measured footprint of the daemon, host memory, load, disk, process tree |
| **Settings** | configuration, write-access state, keyboard reference |

## Failure behaviour

| failure | behaviour |
|---|---|
| a mirror is missing | `present: false`, the panel says the source is missing, the rest still renders |
| git is not installed | mirrors cannot be created; doctor says so with the install command |
| GitHub is rate-limited or offline | last good copy from disk + `stale: true` shown in the panel |
| the daemon is down | the deck shows "the deck cannot see the agency" rather than stale numbers |
| a source file is malformed | that record is skipped, the rest of the panel renders |
| write mode requested without a token | `/api/action` returns 409 with the reason; the UI shows the exact command instead |
| a mirror has uncommitted changes | sync skips it and says so; nothing is discarded |
