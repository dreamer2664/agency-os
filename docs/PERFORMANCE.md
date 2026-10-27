# Performance

Target: **≈300 MB** total for the environment *and a browser*, on a Debian sandbox with 2 GB RAM.
Method: real `/proc` measurement, both PSS (shared pages divided between sharers) and summed RSS
(the double-counting upper bound). Results and the verdict: [`MEASUREMENTS.md`](MEASUREMENTS.md).

## The short version

| component | measured | share of a 300 MB budget |
|---|---|---|
| `agencyd` (the entire environment) | **24–30 MB**, 1 process | 8–10 % |
| the deck over a blank page | **+44 MB** of browser memory | 15 % |
| Chromium's own baseline (blank page) | **393 MB** | 131 % |

The daemon is not the problem and never was. A Chromium on this host costs more than the entire
budget before it has loaded a single byte of the deck. The closest achievable configuration —
Chromium `--single-process` kiosk mode — lands at **347 MB median / 352 MB peak** on the published
commit (326–347 MB across four runs), i.e. 15.7 % over target; that is what `scripts/kiosk.sh`
ships and what run #1 in `MEASUREMENTS.md` shows. The target is not met.

Nothing here is concealed by excluding a process: the budget line includes the browser, the
display server is Xvfb (not a desktop environment), and the daemon figure is its whole process
tree. The ad-hoc measurements that led to the kiosk configuration are listed too.

## Design decisions that keep it small

**No framework, no build step, no npm.** 13 ES modules (2 700 lines), one 870-line CSS file, one
57-line HTML file. No external
font request, no icon library, no CDN (the deck is also served under a CSP that forbids one).
Icons are inline SVG paths; the brand mark is one SVG.

**One process.** Python's `ThreadingHTTPServer`. No gunicorn/uvicorn/workers/supervisor, no
message broker, no database, no Redis, no Node runtime. The stdlib is the whole dependency list.

**Lazy modules.** A panel's module is fetched the first time it is opened; the first screen only
needs `app.js` and the overview.

**Per-version cache.** `State.cached(key, builder)` memoises every derived structure against a
version counter. The counter moves only when the filesystem signature moves, so an idle deck does
no work. Measured on the live board (292 cards): **cold 124 ms, warm 0.01 ms** for `/api/summary`.
`test_summary_stays_fast_with_a_large_board` asserts the same shape at **4 000 cards**: warm
< 50 ms (a cache hit), cold build bounded.

**Virtualised lists.** Fixed-row virtualisation renders ~30 nodes for 292 cards or 1 521 wire
lines; scrolling re-renders only the visible window on `requestAnimationFrame`.

**Bounded everything.** Every list endpoint caps (`limit ≤ 500`), search keeps only the newest
matches while streaming the file, JSONL tails read at most the last 1 MB, per-file caches key on
`(mtime, size)` so a growing bus file is not re-parsed, logs rotate at 2 MB, the GitHub cache is
bounded by TTL and keyed by URL.

**Cheap change detection.** The watcher polls directory `mtime`s plus the size/mtime of
`.git/HEAD`, `PUSHES.md`, `ORDERS.md`, `TOWER.md` and `STATUS.md` every 4 s — a handful of stat
calls, not a scan of 292 JSON files.

**Push instead of poll.** The browser holds one SSE stream. When the version moves, the panel
re-fetches itself once (debounced 300 ms). There is no `setInterval` fetch loop anywhere in the
deck; the clock updates text nodes once a second and nothing else.

**Compositor hygiene.** The boot splash is removed from the DOM after it fades (a hidden element
with running animations still costs layers). Animations are transform/opacity only, and
`prefers-reduced-motion` disables them.

**gzip + ETags.** JSON over 1 KB, CSS and JS are gzipped when the client accepts it;
`/api/summary` and static files carry ETags and answer `304`.

**No idle timers in the daemon.** Two background threads total: the filesystem watcher and an
optional ff-only pull loop (default 180 s, `sync_interval = 0` disables it).

## What the numbers do *not* include

* No desktop environment, no window manager, no display manager — the "desktop" is the deck.
  Xvfb (kiosk mode) is measured inside the browser figure's parent tree where applicable.
* No kernel page-cache effects are subtracted: `MemAvailable` in `/proc/meminfo` is reported as
  the host's free-memory figure, not as a claim about Agency OS.
* Nothing is estimated. Where a number came from an ad-hoc run instead of the script, the table
  says so.

## Regression guardrails

| guardrail | where |
|---|---|
| warm summary over 4 000 cards < 50 ms, cold < 6 s | `tests/run_all.py::test_summary_stays_fast_with_a_large_board` |
| no dependency may be added without an entry in `CHANGELOG.md` | `CONTRIBUTING.md` |
| `agencyos status` prints live daemon RSS/PSS | `agencyd/cli.py` |
| Resources panel reads `/proc` per request | `agencyd/resources.py` |
| a new panel must page/virtualise its lists | `AGENTS.md` § Performance rules |
| `scripts/measure.sh` before and after any UI work | `CONTRIBUTING.md` |
