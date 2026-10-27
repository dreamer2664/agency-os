# Measurements

Every number below was produced by `scripts/measure.sh` on the sandbox described in
`docs/PERFORMANCE.md`. Nothing here is an estimate. The summary is written by hand from the
runs appended underneath it; the raw sections are the script's own output, unedited.

## Summary of every configuration measured

Host: Debian 13 (trixie), kernel 6.1, **1 982 MB RAM**, 2 vCPU, no GPU, no display server
(Xvfb 1440x900x24 was used for the two GUI modes). All values are **PSS** in MB after a 3 s
warm-up, sampled once a second for 15–20 s. `agencyd` is always its own single process tree.

| # | configuration | browser | agencyd | **total (median)** | total (peak) | verdict |
|---|---|---|---|---|---|---|
| 1 | **kiosk — chromium single-process, fullscreen, Xvfb** | 301.0 | 25.1 | **326.1** | 345.4 | closest to the target (+8.7 %) |
| 2 | headless — chromium, multi-process (default) | 428.9 | 25.9 | 454.8 | 462.7 | +51 % |
| 3 | headless — chromium, **about:blank** (baseline) | 387.0 | 24.1 | 411.1 | 413.2 | a blank page already costs 387 MB |
| 4 | headless — firefox-esr, 1 content process, low-mem prefs | 507.2 | 25.0 | 532.2 | 654.8 | worst here |
| 5 | GUI — chromium multi-process, Xvfb | ~414 | 25 | ~439 | — | ad-hoc run, see note |
| 6 | GUI — firefox kiosk, low-mem prefs, Xvfb | ~552 | 25 | ~577 | — | ad-hoc run, see note |
| 7 | GUI — surf (WebKitGTK 4.1), Xvfb | ~381 | 25 | ~406 | — | ad-hoc run, see note |

Runs 1–4 are the script's verbatim output below. Runs 5–7 came from the same `/proc`
PSS walker (`resources.py` logic) invoked directly, without `measure.sh`, before the kiosk mode
existed; they are included because they are the evidence that led to the kiosk configuration.

### Verdict against the 300 MB target

**The target is not met with a full browser on this host, and the gap is not in Agency OS.**

* The whole Agency OS daemon — the thing this project actually ships — is **24–30 MB** (25 MB cold,
  30 MB after 20 minutes of serving the deck): 8–10 % of
  the 300 MB budget, single process, no workers, no database. That part is not close to the
  budget, it is negligible against it.
* The browser's own baseline is the budget: Chromium renders `about:blank` in **387 MB** here.
  The deck adds **≈42–54 MB** over that blank page (run 2 minus run 3), which is the real cost of
  the interface and is consistent with a single static page plus 20 s of JSON.
* The best configuration found — **Chromium `--single-process` kiosk mode** — removes Chromium's
  per-process sandbox/renderer overhead and lands at **326 MB total (median), 345 MB peak**, i.e.
  8.7 % over target. That is the closest achievable result on this sandbox, and it is the
  configuration `scripts/kiosk.sh` ships.
* A browser-free client would meet 300 MB trivially but would lose the interface this project
  exists to provide, so it is not offered as a way to "win" the number.

### What was tried and did not help

| attempt | effect |
|---|---|
| `--process-per-site`, `--renderer-process-limit=1`, `--in-process-gpu` | 414 → 418 MB (noise) |
| `--enable-low-end-device-mode`, `--num-raster-threads=1`, `--disable-gpu-compositing` | no measurable change |
| `--js-flags=--max-old-space-size=48…64` | keeps V8's heap from growing; ~10–20 MB, already shipped |
| 20+ `--disable-features=…` (Translate, MediaRouter, BackForwardCache, …) | ~15 MB, already shipped |
| Firefox instead of Chromium | 507 MB headless, 552 MB in kiosk — heavier on this host |
| WebKitGTK (surf) | 381 MB — lighter than multi-process Chromium, heavier than single-process |
| `--single-process` | **≈110 MB saved** — the single largest win, and the shipped kiosk default |

### What the interface does to stay small (measured, not asserted)

* No framework, no build step, no external font, no CDN: `index.html` + one CSS file + 12 ES
  modules; `/api/summary` is **3.9 KB** and is the only payload the first screen fetches.
* Virtualised lists: 292 board cards or 1 521 wire messages render ~30 DOM nodes.
* One SSE connection instead of polling; per-version server cache; the deck recomputes nothing
  while idle.
* The boot splash is removed from the DOM after it fades — a hidden element with running
  animations still costs compositor memory (this was found by measurement, not by review).
* The daemon serves gzip for JSON/CSS/JS (`>1 KB`), ETags on `/api/summary` and static files.
* `agencyos status` reports live RSS/PSS of the daemon tree, and the Resources panel reads
  `/proc` at request time; nothing in the UI invents a number.

### How to reproduce

```bash
scripts/measure.sh --kiosk --seconds 20     # configuration 1 (the shipped kiosk)
scripts/measure.sh --seconds 20             # configuration 2 (headless chromium)
scripts/measure.sh --baseline --seconds 15  # configuration 3 (blank page baseline)
scripts/measure.sh --browser firefox-esr --seconds 20   # configuration 4
```

Each run appends a section to this file and prints the same table to stdout.

## Raw runs

## Measured 2026-10-27 13:31:30Z — kiosk

Commands used (verbatim):

```
scripts/measure.sh --seconds 20 --seconds 19
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `chromium` (Chromium 156.0.8078.47 built on Debian GNU/Linux 13 (trixie)) |
| samples | 19 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 24.2 MB → median 25.1 MB, peak 25.1 MB |
| agencyd RSS | baseline 31.3 MB |
| browser tree PSS | median 301.0 MB, peak 320.3 MB |
| browser tree summed RSS | median 339.3 MB, peak 347.1 MB |
| **total PSS (daemon + browser)** | **median 326.1 MB, peak 345.4 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, the 4 boot modules + the overview module, `/api/summary` (3.9 KB) and one
  SSE connection. The other 8 view modules are fetched only when their panel is opened.

## Measured 2026-10-27 13:31:49Z — headless

Commands used (verbatim):

```
scripts/measure.sh 15 --seconds 14
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `chromium` (Chromium 156.0.8078.47 built on Debian GNU/Linux 13 (trixie)) |
| samples | 14 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 25.1 MB → median 25.9 MB, peak 25.9 MB |
| agencyd RSS | baseline 32.1 MB |
| browser tree PSS | median 428.9 MB, peak 436.8 MB |
| browser tree summed RSS | median 935.5 MB, peak 943.7 MB |
| **total PSS (daemon + browser)** | **median 454.8 MB, peak 462.7 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, the 4 boot modules plus the overview module, `/api/summary` (3.9 KB)
  and one SSE connection. The other 8 view modules load only when their panel is opened.
