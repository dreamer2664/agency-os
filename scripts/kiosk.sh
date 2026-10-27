#!/usr/bin/env bash
# Agency OS — kiosk session: the deck as the only thing on the machine.
#
#   scripts/kiosk.sh                 start Xvfb + the daemon + a fullscreen browser
#   scripts/kiosk.sh --display :1    use an existing X display instead of Xvfb
#   scripts/kiosk.sh --browser firefox
#
# Measured footprint of this configuration (Chromium single-process, 1440x900,
# daemon included) is in docs/MEASUREMENTS.md. Chromium's single-process mode is
# a kiosk trade-off: one process, no renderer sandbox, lowest memory. The page is
# a local static deck, so the usual multi-tab risks do not apply.
#
# Quit: Ctrl-Alt-Q (or `pkill -x chromium` / `agencyos down`).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPLAY_ARG=""
BROWSER_PREF="chromium"
PORT="${AGENCY_OS_PORT:-8787}"
W=1440; H=900
while [ $# -gt 0 ]; do
  case "$1" in
    --display) DISPLAY_ARG="$2"; shift 2 ;;
    --browser) BROWSER_PREF="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --size) W="${2%x*}"; H="${2#*x}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

say() { printf '\033[38;5;179m▸\033[0m %s\n' "$*"; }

# --- daemon -----------------------------------------------------------------
export AGENCY_OS_PORT="$PORT"
if ! "$ROOT/bin/agencyos" status >/dev/null 2>&1 || ! curl -sf "http://127.0.0.1:${PORT}/api/ping" >/dev/null; then
  say "starting agencyd on port ${PORT}"
  "$ROOT/bin/agencyos" up --port "$PORT" || exit 1
fi
URL="http://127.0.0.1:${PORT}/"

# --- display ----------------------------------------------------------------
XVFB_PID=""
if [ -n "$DISPLAY_ARG" ]; then
  export DISPLAY="$DISPLAY_ARG"
  say "using display ${DISPLAY}"
else
  command -v Xvfb >/dev/null 2>&1 || {
    echo "Xvfb is not installed. Either install it (sudo apt-get install -y --no-install-recommends xvfb)" >&2
    echo "or open ${URL} in the browser you already have." >&2
    exit 1
  }
  N=99
  while [ -e "/tmp/.X${N}-lock" ]; do N=$((N + 1)); done
  Xvfb ":${N}" -screen 0 "${W}x${H}x24" -nolisten tcp >/tmp/agencyos-xvfb.log 2>&1 &
  XVFB_PID=$!
  export DISPLAY=":${N}"
  sleep 1
  say "Xvfb on ${DISPLAY} (pid ${XVFB_PID})"
fi
cleanup() {
  [ -n "${BPID:-}" ] && kill "$BPID" 2>/dev/null
  [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null
  [ -n "${PROFILE:-}" ] && rm -rf "$PROFILE"
}
trap cleanup EXIT INT TERM

# --- browser ----------------------------------------------------------------
PROFILE=$(mktemp -d /tmp/agencyos-kiosk.XXXXXX)
case "$BROWSER_PREF" in
  chromium*)
    BIN=$(command -v chromium || command -v chromium-browser) || {
      echo "chromium not found" >&2; exit 1; }
    BASE=(--disable-dev-shm-usage --disable-gpu --in-process-gpu
          --disable-extensions --disable-sync --disable-background-networking
          --disable-component-update --disable-default-apps --disable-breakpad
          --metrics-recording-only --mute-audio --no-pings --disable-domain-reliability
          --no-first-run --no-default-browser-check --disable-translate
          --js-flags=--max-old-space-size=64
          --disable-features=Translate,MediaRouter,OptimizationHints,GlobalMediaControls,CalculateNativeWinOcclusion,BackForwardCache
          --user-data-dir="$PROFILE" --window-position=0,0 --window-size="${W},${H}"
          --start-fullscreen --app="$URL")
    # In a container or as an unprivileged user without user namespaces, Chromium
    # needs --no-sandbox; --test-type suppresses the "unsupported flag" infobar it
    # would otherwise draw across the top of the deck.
    if [ "$(id -u)" = "0" ] || [ ! -e /proc/sys/kernel/unprivileged_userns_clone ] \
       || [ "$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo 1)" = "0" ]; then
      BASE+=(--no-sandbox --test-type)
    fi

    launch() {  # $@: extra flags
      "$BIN" "${BASE[@]}" "$@" >/tmp/agencyos-kiosk.log 2>&1 &
      BPID=$!
    }

    say "chromium kiosk (single process, lean flags) → ${URL}"
    launch --single-process --no-zygote
    # --single-process is a large memory win but crashes on some kernels during
    # startup. If it does not survive the first seconds, fall back and say so
    # rather than leaving a blank display.
    for _ in 1 2 3 4; do
      sleep 1
      kill -0 "$BPID" 2>/dev/null || break
    done
    if ! kill -0 "$BPID" 2>/dev/null; then
      say "chromium exited in single-process mode — retrying multi-process (higher memory)"
      PROFILE=$(mktemp -d /tmp/agencyos-kiosk.XXXXXX)
      BASE=("${BASE[@]/--user-data-dir=*/--user-data-dir=$PROFILE}")
      launch
    fi
    ;;
  firefox*)
    BIN=$(command -v firefox-esr || command -v firefox) || {
      echo "firefox not found" >&2; exit 1; }
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
    say "firefox kiosk (low-memory prefs) → ${URL}"
    "$BIN" --no-remote --kiosk --profile "$PROFILE" "$URL" >/tmp/agencyos-kiosk.log 2>&1 &
    BPID=$!
    ;;
  *) echo "unknown browser ${BROWSER_PREF}" >&2; exit 2 ;;
esac

sleep 2
if kill -0 "$BPID" 2>/dev/null; then
  say "the deck is up. Ctrl-C here (or close the window) to end the session."
else
  echo "the browser exited — see /tmp/agencyos-kiosk.log (or open ${URL} yourself)" >&2
  exit 1
fi
wait "$BPID" 2>/dev/null
