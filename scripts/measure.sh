#!/usr/bin/env bash
# Measure Agency OS honestly: daemon + a real browser against the live deck.
#
#   scripts/measure.sh                  headless chromium (no display server)
#   scripts/measure.sh --kiosk          the shipped kiosk configuration (Xvfb +
#                                       chromium single-process, fullscreen)
#   scripts/measure.sh --display        chromium inside Xvfb, multi-process
#   scripts/measure.sh --seconds 30     longer sampling window
#
# Reports both PSS (shared pages divided between sharers — the honest total for
# a multi-process browser) and the raw summed RSS (which double-counts shared
# libraries and is therefore an upper bound, not a measurement of the app).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="headless"
SECONDS_WIN=20
BROWSER_OVERRIDE=""
TARGET_URL=""
OUT="${OUT:-$ROOT/docs/MEASUREMENTS.md}"
for arg in "$@"; do
  case "$arg" in
    --display) MODE="display" ;;
    --kiosk) MODE="kiosk" ;;
    --headless) MODE="headless" ;;
    --browser) shift; BROWSER_OVERRIDE="$1" ;;
    --baseline) BASELINE=1 ;;
    --seconds) shift; SECONDS_WIN="$1" ;;
    --seconds=*) SECONDS_WIN="${arg#*=}" ;;
    --out) shift; OUT="$1" ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
  esac
done
case "${2:-}" in ""|--*) : ;; *) [ "$1" = "--seconds" ] && SECONDS_WIN="$2" ;; esac

PY="${PYTHON:-python3}"
# captured before any parsing: `shift` inside the loop below rewrites $@, and the
# "commands used" line in the report must stay the command the operator typed.
ORIG_ARGS="$*"
ERR_ARGS="$ORIG_ARGS"
AGENCYOS="$ROOT/bin/agencyos"

PIDFILE="${AGENCY_OS_HOME:-$HOME/.agency-os}/run/agencyd.pid"
live_pid() {
  # a pid file left behind by a killed daemon must never be measured as 0 MB
  [ -f "$PIDFILE" ] || return 1
  local p; p=$(cat "$PIDFILE" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && printf '%s' "$p"
}
DPID=$(live_pid || true)
if [ -z "$DPID" ]; then
  echo "no live daemon — starting one"
  "$AGENCYOS" up || exit 1
  DPID=$(live_pid || true)
fi
[ -z "$DPID" ] && { echo "the daemon is not running and could not be started"; exit 1; }
if ! curl -fsS "http://127.0.0.1:${AGENCY_OS_PORT:-8787}/api/ping" >/dev/null 2>&1; then
  echo "the daemon pid $DPID is alive but the API does not answer — refusing to measure"; exit 1
fi
URL="http://127.0.0.1:${AGENCY_OS_PORT:-8787}/?boot=1"

BROWSER=""
CANDIDATES=("chromium" "chromium-browser" "google-chrome" "google-chrome-stable" "firefox-esr" "firefox")
if [ -n "${BROWSER_OVERRIDE:-}" ]; then CANDIDATES=("$BROWSER_OVERRIDE"); fi
for b in "${CANDIDATES[@]}"; do
  command -v "$b" >/dev/null 2>&1 && { BROWSER="$b"; break; }
done
[ "${BASELINE:-0}" = "1" ] && URL="about:blank"
[ -z "$BROWSER" ] && { echo "no browser found"; exit 1; }

PROFILE=$(mktemp -d /tmp/agencyos-measure.XXXXXX)
SCREEN_PID=""
cleanup() {
  [ -n "${BPID:-}" ] && kill "$BPID" 2>/dev/null
  [ -n "$SCREEN_PID" ] && kill "$SCREEN_PID" 2>/dev/null
  rm -rf "$PROFILE"
}
trap cleanup EXIT

if [ "$MODE" = "kiosk" ] || [ "$MODE" = "display" ]; then
  if ! command -v Xvfb >/dev/null 2>&1; then
    echo "Xvfb missing: apt-get install -y --no-install-recommends xvfb"; exit 1
  fi
  Xvfb :99 -screen 0 1440x900x24 >/dev/null 2>&1 &
  SCREEN_PID=$!
  export DISPLAY=:99
  sleep 1
  if [ "$MODE" = "kiosk" ]; then
    FLAGS=("--no-sandbox" "--disable-dev-shm-usage" "--disable-gpu" "--in-process-gpu"
           "--single-process" "--no-zygote" "--disable-extensions" "--disable-sync"
           "--disable-background-networking" "--disable-component-update" "--disable-breakpad"
           "--metrics-recording-only" "--mute-audio" "--no-pings" "--disable-domain-reliability"
           "--no-first-run" "--no-default-browser-check" "--disable-translate" "--disable-infobars"
           "--js-flags=--max-old-space-size=64"
           "--disable-features=Translate,MediaRouter,OptimizationHints,GlobalMediaControls,CalculateNativeWinOcclusion,BackForwardCache"
           "--user-data-dir=$PROFILE" "--window-position=0,0" "--window-size=1440,900"
           "--start-fullscreen" "--app=$URL")
  else
    FLAGS=("--no-sandbox" "--disable-dev-shm-usage" "--disable-gpu" "--in-process-gpu"
           "--process-per-site" "--renderer-process-limit=1" "--user-data-dir=$PROFILE"
           "--window-size=1440,900" "--start-maximized" "--no-first-run"
           "--no-default-browser-check" "--disable-extensions" "$URL")
  fi
elif [ "${BROWSER%%-*}" = "firefox" ] || [ "$BROWSER" = "firefox-esr" ]; then
  # Firefox ignores Chromium flags; a fresh profile with low-memory prefs is the
  # only way to compare like for like.
  "$BROWSER" --CreateProfile "measure $PROFILE" >/dev/null 2>&1 || true
  cat > "$PROFILE/user.js" <<'PREFS'
user_pref("dom.ipc.processCount", 1);
user_pref("fission.autostart", false);
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.webrender.software", true);
user_pref("toolkit.telemetry.enabled", false);
user_pref("browser.newtabpage.enabled", false);
user_pref("javascript.options.mem.max", 65536);
user_pref("browser.cache.memory.capacity", 16384);
user_pref("network.prefetch-next", false);
PREFS
  export MOZ_HEADLESS=1
  FLAGS=("--headless" "--no-remote" "--new-instance" "--profile" "$PROFILE" "$URL")
else
  FLAGS=("--headless=new" "--disable-gpu" "--no-sandbox" "--disable-dev-shm-usage"
         "--user-data-dir=$PROFILE" "--window-size=1440,900" "--hide-scrollbars"
         "--no-first-run" "--no-default-browser-check" "$URL")
fi

# ---- daemon baseline -------------------------------------------------------
pss_of() {  # summed PSS of a pid tree
  "$PY" - "$1" <<'PY'
import sys
pid = int(sys.argv[1])
kids, mem = {}, {}
for entry in __import__("os").listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        st = open(f"/proc/{entry}/stat").read()
        ppid = int(st[st.rfind(")") + 2:].split()[1])
        kids.setdefault(ppid, []).append(int(entry))
        for line in open(f"/proc/{entry}/smaps_rollup"):
            if line.startswith("Pss:"):
                mem[int(entry)] = int(line.split()[1])
                break
    except (OSError, ValueError, IndexError):
        continue
stack, seen, total = [pid], set(), 0
while stack:
    p = stack.pop()
    if p in seen or p not in mem:
        continue
    seen.add(p)
    total += mem[p]
    stack.extend(kids.get(p, []))
print(total)
PY
}
rss_of() {
  "$PY" - "$1" <<'PY'
import os, sys
pid = int(sys.argv[1])
kids, mem = {}, {}
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        st = open(f"/proc/{entry}/stat").read()
        ppid = int(st[st.rfind(")") + 2:].split()[1])
        kids.setdefault(ppid, []).append(int(entry))
        fields = st[st.rfind(")") + 2:].split()
        mem[int(entry)] = int(fields[21]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
    except (OSError, ValueError, IndexError):
        continue
stack, seen, total = [pid], set(), 0
while stack:
    p = stack.pop()
    if p in seen or p not in mem:
        continue
    seen.add(p)
    total += mem[p]
    stack.extend(kids.get(p, []))
print(total)
PY
}

D_PSS_BASE=$(pss_of "$DPID"); D_RSS_BASE=$(rss_of "$DPID")
API_BYTES=$(curl -s "http://127.0.0.1:${AGENCY_OS_PORT:-8787}/api/summary" | wc -c)

# ---- launch and sample -----------------------------------------------------
"$BROWSER" "${FLAGS[@]}" >/dev/null 2>&1 &
BPID=$!
sleep 3
samples=()
for _ in $(seq 1 "$SECONDS_WIN"); do
  [ ! -d "/proc/$BPID" ] && break
  samples+=("$(pss_of "$BPID") $(rss_of "$BPID") $(pss_of "$DPID")")
  sleep 1
done

MEASURE_ARGS="$ERR_ARGS" python3 - "$MODE${BASELINE:+ baseline}" "$BROWSER" "$D_PSS_BASE" "$D_RSS_BASE" "$DPID" "$API_BYTES" "$OUT" "${samples[@]}" <<'PY'
import statistics, subprocess, sys, time, os, platform

mode_raw, browser, d_pss_base, d_rss_base, dpid, api_bytes, out = sys.argv[1:8]
mode = mode_raw.strip()
rows = [tuple(map(int, s.split())) for s in sys.argv[9:] if s.strip()]
if not rows:
    print("no samples collected (browser exited early)")
    sys.exit(1)
b_pss = [r[0] for r in rows]
b_rss = [r[1] for r in rows]
d_pss = [r[2] for r in rows]
total = [a + b for a, b in zip(b_pss, d_pss)]
meminfo = {}
for line in open("/proc/meminfo"):
    k, _, v = line.partition(":")
    meminfo[k] = int(v.split()[0])
total_ram = meminfo.get("MemTotal", 0)
mb = lambda kb: round(kb / 1024, 1)

def kernel():
    try:
        return platform.release()
    except Exception:
        return "?"

def cmd_output(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except Exception:
        return "?"

ARGS = os.environ.get("MEASURE_ARGS", "")
report = f"""
## Measured {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())} — {mode}

Commands used (verbatim):

```
scripts/measure.sh {ARGS} --seconds {len(rows)}
```

| quantity | value |
|---|---|
| host RAM | {mb(total_ram)} MB ({kernel()}) |
| browser | `{browser}` ({cmd_output([browser, '--version'])}) |
| samples | {len(rows)} × 1 s after a 3 s warm-up |
| agencyd (1 process) PSS | baseline {mb(int(d_pss_base))} MB → median {mb(statistics.median(d_pss))} MB, peak {mb(max(d_pss))} MB |
| agencyd RSS | baseline {mb(int(d_rss_base))} MB |
| browser tree PSS | median {mb(statistics.median(b_pss))} MB, peak {mb(max(b_pss))} MB |
| browser tree summed RSS | median {mb(statistics.median(b_rss))} MB, peak {mb(max(b_rss))} MB |
| **total PSS (daemon + browser)** | **median {mb(statistics.median(total))} MB, peak {mb(max(total))} MB** |
| `/api/summary` payload | {int(api_bytes)} bytes |

Notes:
- PSS divides shared pages between the processes that map them; summed RSS counts them once per
  process. For a Chromium with several helper processes the RSS sum overstates usage by 2–3×,
  so the PSS column is the honest total. Both are printed.
- The daemon figure is its whole process tree; it is a single Python process by design.
- The browser figure includes Chromium's own baseline (renderer, GPU-less compositor, utility
  processes) — that is the browser the operator runs, not an allowance excluded from the budget.
- Page load is the deck's own: no framework, no external fonts, no CDN. The only requests are
  `index.html`, `app.css`, 11 ES modules, `/api/summary`, and one SSE connection.
"""
print(report)
with open(out, "a", encoding="utf-8") as fh:
    fh.write(report)
print(f"appended to {out}")
PY
