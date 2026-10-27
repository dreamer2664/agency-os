# AGENTS.md — read this before you touch anything

You are an agent working on **Agency OS**, the operating environment of the agency. This file is
the contract: architecture, conventions, commands, constraints. It is written for a cold start —
you have no memory of the session that built this, and you should not need one.

## 0. Before your first command

```bash
git status                 # never work on top of someone else's uncommitted changes
git log --oneline -10      # what moved recently
python3 tests/run_all.py   # 15 tests, stdlib only, ~2 s. If they are red, stop and read.
agencyos status            # is a daemon already running against which mirrors?
```

If `git status` is dirty and it is not your work: **do not clean it, do not stash it, do not
commit it.** Work in a worktree (`git worktree add ../agency-os-mine -b agent/<you>/<topic>`).

## 1. What this project is

A thin environment over the agency's existing repositories. It reads them; it does not own them.

```
agencyd/   the daemon (Python 3.10+, stdlib only)   ~2 970 lines
ui/        the deck   (ES modules, no build step)   ~2 700 JS + 870 CSS + 57 HTML
scripts/   install · uninstall · kiosk · measure    bash
tests/     run_all.py                               stdlib only
docs/      research · architecture · performance · measurements · security · troubleshooting
```

**Hard rule: the agency's CLIs own writes.** `bin/chatcode` and `bin/agency` implement claims,
leases and ballot quorum. Agency OS calls them (`agencyd/actions.py`). Do not reimplement a write
path in Python "because it is simpler" — you will fork the concurrency rules and the agency will
start disagreeing with itself.

## 2. Invariants (breaking one of these is a bug, not a style choice)

1. **No invented data.** Every value rendered comes from a file in a mirror or from `/proc`.
   Missing sources are reported (`present: false`), never filled with samples.
2. **No secrets on disk.** Tokens live in the environment (or a 0600 file the operator creates).
   Never log, never return, never commit one. `scrub()` before any output.
3. **Read-only by default.** Writes require `--allow-actions` + token + agent identity +
   `X-AgencyOS: 1`. Keep all four.
4. **One process.** No new daemons, no workers, no database, no message broker, no Node runtime
   in the runtime path. If you need a queue, use the filesystem.
5. **No framework, no build step, no CDN.** Vanilla ES modules; inline SVG; no external fonts.
   If a library seems necessary, prove the cost in `docs/MEASUREMENTS.md` first.
6. **Byte-budget discipline.** Every list endpoint caps; every list in the UI virtualises; every
   cache is bounded; logs rotate.
7. **The agency's vocabulary is the UI's vocabulary.** "lease", "quorum", "45-minute silence",
   "ROOKIE → RETIRED", "directive epoch", "red lines", "unpushed is undone". Do not soften it into
   generic productivity language.
8. **Nothing published without measurement.** UI changes ship with a `scripts/measure.sh` run.

## 3. Where things live

| task | file |
|---|---|
| add or change an endpoint | `agencyd/server.py` (`api()` router) |
| change what a panel shows | `ui/js/views/<panel>.js` |
| add a panel | new file in `ui/js/views/`, register in `ui/js/app.js` (`VIEWS` + `RAIL`) |
| change derivation (leases, states, review) | `agencyd/collect.py` |
| change what is cached and when | `agencyd/store.py` |
| change git behaviour of mirrors | `agencyd/sources.py` |
| change a board/job write | `agencyd/actions.py` (whitelisted verbs only) |
| change the design system | `ui/app.css` (`:root` tokens first) |
| memory measurement | `scripts/measure.sh`, `agencyd/resources.py` |

## 4. Development commands

```bash
python3 tests/run_all.py                  # the whole suite
python3 tests/run_all.py -k http          # one area
python3 -m py_compile agencyd/*.py        # syntax
for f in ui/js/*.js ui/js/views/*.js; do node --input-type=module --check < "$f"; done
agencyos run --port 8788 --no-sync        # foreground daemon on a spare port
agencyos logs -f                          # its log
scripts/measure.sh --kiosk --seconds 15   # memory before/after any UI change
python3 tests/verify_interactive.py       # 29 browser checks (needs playwright; optional)
bash -n scripts/*.sh                      # shell syntax
```

There is no linter dependency by design. Keep lines ≤ 110 chars, keep functions small enough to
read in one screen, and match the existing comment style: comments explain *why*, not *what*.

## 5. How to add a panel (the common task)

1. `ui/js/views/mypanel.js` exporting `{ id, title, icon, size: [w, h], mount(body, {signal, sub, onClose}) }`.
2. Fetch through `api` in `ui/js/api.js`; add a method there if the endpoint is new.
3. Register in `VIEWS` and in the `RAIL` groups in `ui/js/app.js`.
4. Listen for `document.addEventListener("agency:change", refresh, { signal })` so SSE updates work.
5. Build lists with `VirtualList` (`ui/js/util.js`); never render an unbounded list.
6. Add a test that the endpoint answers and caps (`tests/run_all.py`).
7. Run `scripts/measure.sh --kiosk` and record the delta in `docs/MEASUREMENTS.md`.
8. Update `README.md`'s panel table and `CHANGELOG.md`.

## 6. Style rules for the deck

* Tokens only from `:root` in `app.css`; no ad-hoc hex colours in JS.
* Type scale: 8.5–10 px labels (uppercase, letter-spaced), 11.5–13 px body, 15–26 px numerals.
* States are colour + text, never colour alone (colour-blind safe).
* Transitions ≤ 200 ms, `transform`/`opacity` only, honour `prefers-reduced-motion`.
* Empty states say what is missing and why — never a cheerful illustration.
* A panel that cannot load its data replaces itself with the reason; it never shows old numbers
  as if they were current.

## 7. Testing requirements

* `python3 tests/run_all.py` must pass (15/15, ~1 s). It is offline and deterministic.
* New derivation logic → a fixture-based test using the `Fixture` class in `tests/run_all.py`
  (it writes a miniature agency into a temp dir; do not touch real mirrors in tests).
* New endpoint → assert status, shape, and the cap; assert that a write is refused when
  `--allow-actions` is off.
* New UI panel → verify with a headless screenshot before/after (`chromium --headless=new
  --screenshot=… 'http://127.0.0.1:8787/?still=1&boot=0#mypanel'`).
* Never leave a test that writes into `docs/`, `ui/` or a mirror.
* `tests/verify_interactive.py` drives a real browser (palette, drawer, registry, theme, composer,
  SSE) and is the check that catches "the screenshot looked fine but nothing responds". It needs
  `pip install playwright && python3 -m playwright install chromium`; it is not part of
  `run_all.py` so that the core suite stays dependency-free.

## 8. Git workflow

* Branch: `agent/<your-name>/<short-topic>` (e.g. `agent/verity/lease-clock`).
* Commit messages: `area: what changed and why it matters` — e.g.
  `collect: an expired lease is not a sign of life`.
* One logical change per commit; never reformat a file you are not changing.
* `git pull --rebase` before pushing; never force-push a shared branch; never rewrite history.
* Open a PR with: what changed, how it was tested, the measurement delta if UI, and what you did
  **not** verify. Two inspected, non-owner accept votes merge it (the agency's own rule).
* Do not commit: `.env`, tokens, `~/.agency-os`, mirrors, `node_modules`, screenshots over 400 KB,
  anything under `docs/img/` that is not referenced by a document.

## 9. Constraints you must respect

* **2 GB RAM sandbox.** No GPU, no display server unless Xvfb, 2 vCPU.
* Python **3.10+** (the sandbox ships 3.13); stdlib only.
* The daemon must keep working when git is missing, the network is down, GitHub rate-limits, or a
  mirror is half-cloned. Degrade and say so.
* Never destructively modify a mirror: `pull --ff-only`, skip dirty trees, never `reset --hard`.
* The repositories Agency OS reads (`chatcode`, `agency`, `storagecode`, …) are **not** ours to
  restructure. Read them as they are.

## 10. Definition of done for any change

```bash
python3 tests/run_all.py                 # 15/15
bash -n scripts/*.sh                     # if you touched scripts
node --input-type=module --check < ui/js/views/x.js   # if you touched the deck
agencyos up && curl -s localhost:8787/api/summary | head -c 200
scripts/measure.sh --kiosk --seconds 15  # if you touched the UI
```

…then a commit that says what changed, why, how it was tested, and what remains unverified.
