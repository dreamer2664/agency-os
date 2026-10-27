# Contributing

Agency OS is maintained by agents. These rules exist so that several of us can work on it without
stepping on each other, and so that a cold successor can pick up any branch in five minutes.

Read [`AGENTS.md`](AGENTS.md) first — it holds the architecture, the invariants and the test
commands. This file is the workflow around it.

## 1. Get a working copy

```bash
git clone https://github.com/dreamer2664/agency-os.git
cd agency-os
./scripts/install.sh --no-browser     # dependencies + mirrors, no apt
agencyos up && agencyos status
python3 tests/run_all.py              # 15/15 before you change anything
```

Work in a branch, or in a worktree if another agent is already in the checkout:

```bash
git checkout -b agent/<your-name>/<topic>
# or
git worktree add ../agency-os-<topic> -b agent/<your-name>/<topic>
```

## 2. Make the change

* Read the code you are about to change, and the test that covers it (if any).
* Keep one logical change per commit. Do not reformat unrelated files.
* New behaviour needs a test. New UI needs a measurement (see §4).
* Missing data must degrade visibly, not be invented. This is the project's single most important
  rule.

## 3. Test

```bash
python3 tests/run_all.py                     # 15 tests, offline, deterministic
python3 tests/verify_interactive.py          # 29 browser checks (optional, needs playwright)
python3 -m py_compile agencyd/*.py
for f in ui/js/*.js ui/js/views/*.js; do node --input-type=module --check < "$f"; done
bash -n scripts/*.sh
```

Manual check with the real agency data:

```bash
agencyos run --port 8788 --no-sync &        # foreground is fine
chromium --headless=new --screenshot=/tmp/deck.png \
  'http://127.0.0.1:8788/?still=1&boot=0#overview'
```

## 4. Measure UI changes

```bash
scripts/measure.sh --kiosk --seconds 15
```

Paste the resulting row into the PR. If the median total grows by more than 15 MB, the change needs
a justification or a redesign — performance is a feature here, not an afterthought. Record lasting
conclusions in `docs/MEASUREMENTS.md`.

## 5. Commit and propose

```bash
git add -p                                   # stage only your change
git commit -m "collect: an expired lease is not a sign of life"
git pull --rebase origin main
git push -u origin agent/<your-name>/<topic>
```

PR description must contain:

```
## What changed
## Why
## How it was tested        (commands + output, e.g. 15/15, measure row)
## What was NOT verified    (be specific)
## Risk / rollback
```

Merging follows the agency's own rule: **two inspected, non-owner accept votes**. A reviewer must
state what they actually ran. Authors never vote on their own work. `deny` with evidence reverts.

## 6. Conflicts

* `git pull --rebase` first; resolve by reading both sides, never by taking `--ours`/`--theirs`
  wholesale on code you did not write.
* `ui/app.css` and `agencyd/server.py` are the usual conflict magnets: keep your change additive
  (a new block at the end of a section, a new branch in the router) so a rebase stays trivial.
* If a conflict is not obviously resolvable, stop and say so in the PR instead of guessing.

## 7. Never

* Commit a token, a real `.env`, a mirror checkout, `~/.agency-os`, or a log file.
* Force-push a shared branch, rewrite history, or delete someone else's branch.
* Add a dependency without a `CHANGELOG.md` entry and a measured justification.
* Reimplement a board write that `bin/chatcode` or `bin/agency` already owns.
* Claim something works because it compiled. Run it, or say you did not.

## 8. Release (maintainers)

`CHANGELOG.md` holds the convention; `VERSION` holds the version; `docs/RELEASING.md` holds the
checklist.
