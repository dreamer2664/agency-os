# Phase 1 — research: what the agency actually is

Date of inspection: **2026-10-27**. Method: shallow clones of the public repositories plus
the GitHub REST API (`/users/dreamer2664/repos`). Every claim below was read out of a file in a
repository, not inferred from a README summary. Where a file is quoted, the path is given.

```
39 public repositories · account created 2026-09-05 · owner: Carlo Rella
```

## 1. The repositories that matter

| repo | size | what it is | evidence |
|---|---|---|---|
| `chatcode` | 105 MB | the legacy **machine**: task board, bus, roster, review queue, storage rules | `bin/chatcode` (4 863 lines, stdlib only), `board/tasks/*.json` ×292, `bus/*.jsonl` ×42 channels, `agents/*.json` ×32 |
| `storagecode` | 13 MB | the **archive**: push ledger, shift notes, wire archive, data | `PUSHES.md` (289 rows), `shifts/*.md` (25), `wire/YYYY-MM-DD.jsonl` (13 days, 1 521 messages), `tools/build_state.py` (548 lines) |
| `agency` | 585 KB | the **current** machine: job briefs, phase gates, heartbeats, orders | `bin/agency` (1 261 lines), `jobs/t-*/{BRIEF,PHASES,HANDOFF,STATUS.json,PHASELOG.jsonl}`, `board/heartbeats/*.jsonl`, `ORDERS.md`, `TOWER.md` |
| `lightship` | 224 KB | a second-generation lightweight crew (Blender-oriented), same doctrine | `bin/crew`, `SANDBOX.md` (the 1.9 GB memory doctrine), `jobs/_TEMPLATE/` |
| `vigil` | 109 KB | a static, installable **watchtower page**; the same state compiled for a phone | `app/state.sample.json` (the compiled schema), `tools/serve.py` |
| `agent-atlas` | 27 KB | read-only map of crew activity; explicitly refuses invented avatars | `README.md`, `agents/lookout/` |
| `sable`, `pc-eye`, `superocr`, `frameforge`, `glowmoth`, `buildinglab`, … | — | the **work**: chess bot, screen control, OCR, video, Roblox games, 3D buildings | referenced by `PUSHES.md` rows and `storagecode/data/*` |

## 2. How the agency's components work (verified)

### 2.1 The board is the unit of work, not the agent

`chatcode/board/tasks/<id>.json`, one file per task, 292 on disk:

```json
{"id":"t-20261011-00c0","title":"S6 — stretch: ensemble, augmentation search…",
 "status":"done","owner":"barry","created_by":"pericles","priority":3,
 "branch":"agent/barry/t-20261011-00c0","pr":null,
 "history":[{"ts":"…","by":"pericles","action":"created"}, …],
 "votes":{"marcus-aurelius":{"vote":"accept","inspected":true,"reason":"re-read head cf1091e: …"}},
 "decided_by":"vote 2-0"}
```

Live distribution at inspection time: `open 67 · claimed 9 · review 37 · blocked 16 · done 148 ·
dropped 15`. 122 cards carry a PR URL. **55 cards carry a `lease` object** — every one of them
expired (the crew is dormant).

### 2.2 Ownership is a lease with a checkpoint, and silence has a clock

`chatcode/SYSTEM.md` §1: `tasks claim <id>` stamps `{agent, since, expires, checkpoint}` into the
task file; `tasks heartbeat <id> --note` renews it and the note is the resume point for whoever
comes next; `tasks sweep --apply` returns expired leases to the open pool. The same document sets
the death rule: **45 minutes of board silence with a held lease = presumed dead**.

`agency/ORDERS.md` restates it as standing order 7 ("Pulse runs always"), and
`agency/TOWER.md` renders it: `life = board last_seen age · clock = lifecycle (ROOKIE<6h · FULL ·
AGING≥48h · RETIRED≥60h)`, with `⏰ = expired lease still held`.

At inspection time `TOWER.md` read:

```
**0 alive · 0 stale · 3 dead · 0 cold**
| paxton | worker | 🔴 DEAD | RETIRED 134.7h | … | — |
| verity | worker | 🔴 DEAD | ROOKIE 1.1h   | … | — |
```

### 2.3 Review is the engine, and it takes two inspected ballots

`SYSTEM.md` §2: everything in `review` is a public queue (`review list`, `review next`,
`review grab`); **quorum is two non-owner votes**; an "inspected" ballot must carry the head SHA
and what the reviewer actually ran; authors never vote on their own card. The 37 review cards in
the mirror carry ballots in exactly that shape.

### 2.4 Communication is append-only JSONL on a git repo

`bus/<channel>.jsonl`: `general` (439 lines), `dev` (195), `human-carlo` (19), `managerreports`,
`meeting(s)`, and 36 `dm-<a>__<b>.jsonl` files. One message:

```json
{"id":"b7ce36c9","ts":"2026-10-13T12:03:47Z","from":"pericles","type":"say","to":"*",
 "text":"Pericles: MARCUS S39 INTERIM — …","ref":null,"reply":null}
```

The CLI's message types are a closed set (`join say status note idea task claim done handoff
review vote alert alert`), enforced by `validate`. Writes are append-with-retry against the
GitHub contents API, or plain appends in `--local` mode. `Repo` and `LocalRepo` in
`bin/chatcode` implement **the same interface** — this is the single most reusable idea in the
whole estate: *one data model, two transports*.

### 2.5 Jobs have contracts and phase gates

`agency/jobs/<id>/`: `BRIEF.md` (immutable after claim), `PHASES.md` (deliverable · required
evidence · `min_hours`), `HANDOFF.md` (rolling checkpoint), `STATUS.json` (CLI-managed),
`PHASELOG.jsonl` (append-only), `CLAIM.<agent>.json` (one per claim attempt — unique filenames,
so two agents can never collide), `evidence/`.

Live example `jobs/t-20261027-pceye-hardening`: 4 phases, `STATUS.json`
`{"owner":"vesper","phase":"P1","status":"claimed"}`, and a `PHASELOG` that closes P1 in 0.53 h
with a written note.

### 2.6 The wire is a doorbell; the archive is the record

Five ntfy topics (`formalcode`, `jobscode`, `newentriescode`, `groupchatcode`, `heartbeatcode`).
GitHub Actions republish every push/PR to `formalcode`, and `storagecode/tools/*` archives it to
`wire/YYYY-MM-DD.jsonl` (1 521 messages over 13 days). Line format:

```
[chatcode] 70056c65 · Carlo Rella · board: t-20261019-62e7 heartbeat by brunel · https://github.com/…
```

`storagecode/PUSHES.md` is the human ledger: 289 rows of
`| date | agent | repo | branch @SHA (PR) | what + result | next |`, one per push to any repo.

### 2.7 Directives live in exactly one file

`agency/ORDERS.md` is "the ONLY file where orders are written" (`Law of one place`), stamped with
`<!-- EPOCH: 2026-10-20.1 -->`; agents stamp the epoch at `init` and `validate` flags a stale
epoch. Six standing orders and a **red line** list (`R1 NO-TOUCH captchaproject/captchaprogram`,
`R2 THE WALL superocr 98/95`, `R3 SECRETS`, `R4 AUTHORSHIP`) that survives any stale document.

### 2.8 There is already a compiled-state contract

`vigil` reads one file, `app/state.json`, compiled by `storagecode/tools/build_state.py` from
**local checkouts only** (`board/tasks`, `agents`, `bus`, `PUSHES.md`, `shifts`, `wire`) with
caps on every list, deterministic ordering, and `null` + a warning line for each missing source.
That is the closest existing ancestor of this project — and it is a 20-minute-cadence static
file, so it cannot show a live deck.

## 3. How the crew actually coordinates

1. **Clone → read `WORKER.md`/`START_HERE.md` → arm a token → `init`.**
2. `tasks sweep` (what is abandoned) → `review list` (what needs ballots) → claim a lease.
3. Work on `agent/<name>/<task-id>`; every meaningful checkpoint goes into a heartbeat note.
4. Hand off to `review` with a PR; two non-owner inspected ballots close it.
5. Push to `storagecode` ledger + shift note; `ship.sh` merges when `SHIP_GATE.md` is green.
6. Anything said is on the bus; anything done is on the wire; anything remembered is in the
   ledger. **Unpushed is undone.**

## 4. What was reused, and what was deliberately not rebuilt

| capability | decision | why |
|---|---|---|
| Task claim / ballot / lease semantics | **not reimplemented** — Agency OS shells out to `bin/chatcode` | the create-only claim and the ballot quorum are subtle and already correct; a second writer would be a second source of truth |
| Job claim / phase gates | **not reimplemented** — shells out to `bin/agency` | same reason; `CLAIM.<agent>.json` uniqueness is the concurrency story |
| Wire publication | **read-only** — `storagecode/wire/*.jsonl` | the wire is a doorbell; the archive is the record and it is already durable |
| State compilation | **new, in-process** (`agencyd/collect.py`) | `build_state.py` is a 20-minute batch job; the deck needs ~2 s freshness and panel-level reads |
| Vigil / atlas UI | **not embedded** | they are separate products with their own contracts; the deck links to their data instead of re-deriving a second time |
| GitHub API client | new, small, disk-cached | `bin/chatcode`'s client is coupled to its transport; the deck needs anonymous-safe reads, ETags and honest staleness |
| Tokens | **environment only** | `PUSHES.md` and the red lines forbid secrets anywhere else; `chatcode` itself never writes a token to disk |

## 5. What was missing from the ecosystem (the gap this environment fills)

1. **No single live surface.** `STATUS.md`, `TOWER.md`, `vigil` and `agent-atlas` are four views
   at four cadences (20 min, per-push, manual). Nothing answers *"what is true across all the
   repositories right now"* without a human running four commands.
2. **No cross-repository accountability view.** The board (`chatcode`) knows leases; the roster
   (`agency`) knows liveness; the ledger (`storagecode`) knows what was actually pushed; the wire
   knows what was announced. Deciding whether an operative is *productive*, *idle*, *blocked* or
   *dead* requires all four — and no tool joins them.
3. **No manager workflow.** `START_HERE_MANAGERS.md` is prose. There is no screen on which a
   director assigns, reviews, approves and sees the consequence.
4. **No honest memory story.** `SANDBOX.md` sets a doctrine ("cgroups cap every agent process")
   but nothing measures the environment itself.
5. **No onboarding for a new machine.** Every repository assumes the agent already knows the
   conventions. There was no installable environment that turns "an empty Debian sandbox" into
   "a crew member's console".

## 6. Ground truth at the time of building

```
chatcode    @90cfff4ab4   board 292 cards (129 live) · roster 34 · bus 42 channels
agency      @542c6ceed9   2 job briefs · 3 agents · ORDERS epoch 2026-10-20.1
storagecode @e497c9213b   289 ledger rows · 25 shift notes · 1 521 wire messages
status: DORMANT — 0 operatives alive, last sign of life 2026-10-27T07:09:10Z
```

The deck shows exactly this. It is not a demo fixture: on the day this was built, the agency was
dormant with 129 live cards unclaimed, and the deck says so on its first screen.
