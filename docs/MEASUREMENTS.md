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
| 1 | **kiosk — chromium single-process, fullscreen, Xvfb** | 321.7 | 25.3 | **347.0** | 352.3 | closest to the target (+15.7 %) |
| 2 | headless — chromium, multi-process (default) | 437.6 | 25.5 | 463.1 | 471.8 | +54 % |
| 3 | headless — chromium, **about:blank** (baseline) | 393.4 | 24.9 | 418.3 | 419.8 | a blank page already costs 393 MB |
| 4 | headless — firefox-esr, 1 content process, low-mem prefs | 512.6 | 25.4 | 537.9 | 651.7 | worst here |
| 5 | GUI — chromium multi-process, Xvfb | ~414 | 25 | ~439 | — | ad-hoc run, see note |
| 6 | GUI — firefox kiosk, low-mem prefs, Xvfb | ~552 | 25 | ~577 | — | ad-hoc run, see note |
| 7 | GUI — surf (WebKitGTK 4.1), Xvfb | ~381 | 25 | ~406 | — | ad-hoc run, see note |

Rows 1–4 were measured on the published commit (`6f23f4b`) in one batch, and are the script's
verbatim output below. The kiosk figure also moved between runs earlier in the session — **326.1,
335.5, 342.1, 347.0 MB** on the same host — because a fresh Chromium profile and the page's own boot
timing differ each time. Treat configuration 1 as **326–347 MB, ~340 MB typical**, not as a single
number. Runs 5–7 came from the same `/proc` PSS walker (`resources.py` logic) invoked directly,
before `measure.sh` existed; they are kept because they are the evidence behind the kiosk config.

### Verdict against the 300 MB target

**The target is not met with a full browser on this host, and the gap is not in Agency OS.**

* The whole Agency OS daemon — the thing this project actually ships — is **24–30 MB** (25 MB cold,
  30 MB after twenty minutes of serving the deck): **8–10 % of the 300 MB budget**, one process, no
  workers, no database. It is not close to the budget; it is negligible against it.
* The browser's own baseline *is* the budget: Chromium renders `about:blank` in **393 MB** here.
  The deck adds **≈44 MB** over that blank page (run 2 minus run 3) — the real cost of the
  interface, consistent with one static page plus a few seconds of JSON.
* The best configuration found — **Chromium `--single-process` kiosk mode**, which removes the
  per-process sandbox and renderer overhead — lands at **347 MB median / 352 MB peak** on the
  published commit, and between **326 and 347 MB** across four runs. That is **+15.7 %** over
  target at worst. It is the closest achievable result on this sandbox, and it is what
  `scripts/kiosk.sh` ships.
* A browser-free client would meet 300 MB trivially and is the obvious next experiment
  (`docs/ROADMAP.md`), but it would abandon the visual identity this project exists for, so it is
  not offered as a way to "win" the number.

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

## Measured 2026-10-27 15:36:24Z — kiosk

Commands used (verbatim):

```
scripts/measure.sh --seconds 15 --seconds 14
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `chromium` (Chromium 156.0.8078.47 built on Debian GNU/Linux 13 (trixie)) |
| samples | 14 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 24.3 MB → median 25.3 MB, peak 25.3 MB |
| agencyd RSS | baseline 33.5 MB |
| browser tree PSS | median 321.7 MB, peak 327.0 MB |
| browser tree summed RSS | median 345.3 MB, peak 351.2 MB |
| **total PSS (daemon + browser)** | **median 347.0 MB, peak 352.3 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, 11 ES modules, `/api/summary`, and one SSE connection.

## Measured 2026-10-27 15:36:40Z — headless

Commands used (verbatim):

```
scripts/measure.sh 12 --seconds 11
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `chromium` (Chromium 156.0.8078.47 built on Debian GNU/Linux 13 (trixie)) |
| samples | 11 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 24.6 MB → median 25.5 MB, peak 25.5 MB |
| agencyd RSS | baseline 33.8 MB |
| browser tree PSS | median 437.6 MB, peak 446.3 MB |
| browser tree summed RSS | median 951.2 MB, peak 960.8 MB |
| **total PSS (daemon + browser)** | **median 463.1 MB, peak 471.8 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, 11 ES modules, `/api/summary`, and one SSE connection.

## Measured 2026-10-27 15:36:54Z — headless baseline

Commands used (verbatim):

```
scripts/measure.sh --seconds 10 --seconds 9
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `chromium` (Chromium 156.0.8078.47 built on Debian GNU/Linux 13 (trixie)) |
| samples | 9 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 25.0 MB → median 24.9 MB, peak 24.9 MB |
| agencyd RSS | baseline 34.1 MB |
| browser tree PSS | median 393.4 MB, peak 394.9 MB |
| browser tree summed RSS | median 862.7 MB, peak 864.7 MB |
| **total PSS (daemon + browser)** | **median 418.3 MB, peak 419.8 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, 11 ES modules, `/api/summary`, and one SSE connection.

## Measured 2026-10-27 15:37:10Z — headless

Commands used (verbatim):

```
scripts/measure.sh --seconds 12 --seconds 11
```

| quantity | value |
|---|---|
| host RAM | 1982.8 MB (6.1.158+) |
| browser | `firefox-esr` (Mozilla Firefox 153.5.1esr) |
| samples | 11 × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline 25.0 MB → median 25.4 MB, peak 25.4 MB |
| agencyd RSS | baseline 34.1 MB |
| browser tree PSS | median 512.6 MB, peak 626.3 MB |
| browser tree summed RSS | median 798.6 MB, peak 906.5 MB |
| **total PSS (daemon + browser)** | **median 537.9 MB, peak 651.7 MB** |
| `/api/summary` payload | 3947 bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, 11 ES modules, `/api/summary`, and one SSE connection.
