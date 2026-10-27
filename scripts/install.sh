#!/usr/bin/env bash
# Agency OS — installer. Safe to re-run: it updates in place and never touches
# any repository the agency owns.
#
#   ./scripts/install.sh              install for the current user
#   ./scripts/install.sh --no-browser do not install a browser
#   ./scripts/install.sh --deps-only  install system dependencies and stop
#
# What it changes on the host:
#   * creates ~/.local/share/agency-os        (repository mirrors, cache)
#   * creates ~/.config/agency-os/            (config.json — never a token)
#   * creates ~/.agency-os/                   (pid, logs, run files)
#   * writes ~/.local/bin/agencyos            (a symlink into this checkout)
#   * with --browser only: apt-get install chromium (+ fonts) via sudo
# Nothing else is touched. Uninstall with scripts/uninstall.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION" 2>/dev/null || echo dev)"
WITH_BROWSER=1
DEPS_ONLY=0
SKIP_SYNC=0
for arg in "$@"; do
  case "$arg" in
    --no-browser) WITH_BROWSER=0 ;;
    --deps-only)  DEPS_ONLY=1 ;;
    --no-sync)    SKIP_SYNC=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[38;5;179m▸\033[0m %s\n' "$*"; }
ok()   { printf '\033[38;5;108m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[38;5;179m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[38;5;167m✗\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1; }

say "Agency OS ${VERSION} — installing from ${ROOT}"

# ---------------------------------------------------------------- dependency
if ! need python3; then
  die "python3 is required (3.10+). On Debian: sudo apt-get install -y python3"
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 - <<'PY' || die "python3 must be at least 3.10 (found $(python3 -V 2>&1))"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
ok "python ${PYV}"

if ! need git; then
  warn "git is not installed — mirrors cannot sync. Install it with: sudo apt-get install -y git"
else
  ok "git $(git --version | awk '{print $3}')"
fi

if [ "$WITH_BROWSER" = "1" ]; then
  if need chromium || need chromium-browser || need google-chrome || need chromium-browser; then
    ok "browser present ($(command -v chromium || command -v chromium-browser || command -v google-chrome))"
  else
    say "no browser found; attempting to install chromium (needs sudo)"
    if need apt-get; then
      if sudo -n true 2>/dev/null || [ "$(id -u)" = "0" ]; then
        SUDO=""; [ "$(id -u)" = "0" ] || SUDO="sudo -n"
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
          chromium fonts-dejavu-core >/tmp/agencyos-apt.log 2>&1 \
          && ok "chromium installed" \
          || warn "chromium install failed (see /tmp/agencyos-apt.log). The deck still works in any browser."
      else
        warn "sudo is not available without a password — skipping browser install"
      fi
    else
      warn "apt-get not found — install a browser manually"
    fi
  fi
fi

[ "$DEPS_ONLY" = "1" ] && { ok "dependencies done"; exit 0; }

# --------------------------------------------------------------------- paths
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/agency-os/src" "$HOME/.config/agency-os" "$HOME/.agency-os/log"
chmod 700 "$HOME/.config/agency-os" 2>/dev/null || true
ln -sfn "$ROOT/bin/agencyos" "$HOME/.local/bin/agencyos"
ok "command: $HOME/.local/bin/agencyos"

# run a one-time self check (writes nothing outside the dirs above)
if python3 "$ROOT/bin/agencyos" --help >/dev/null 2>&1; then
  ok "cli responds"
else
  die "the cli does not run — python3 $(python3 -V 2>&1) cannot import agencyd"
fi

# --------------------------------------------------------------------- sync
if [ "$SKIP_SYNC" = "1" ]; then
  warn "skipping mirror sync (--no-sync); run: agencyos sync"
elif need git; then
  say "cloning repository mirrors (blobless + sparse: a few MB, not hundreds)"
  if python3 "$ROOT/bin/agencyos" sync; then
    ok "mirrors ready"
  else
    warn "some mirrors could not be fetched — the deck will show the ones that exist and say the rest are missing"
  fi
fi

# ------------------------------------------------------------------- verdict
cat <<TXT

  Agency OS ${VERSION} is installed.

    agencyos up        start the deck in the background
    agencyos status    daemon, board and crew at a glance
    agencyos open      open it in a browser
    agencyos measure --browser --json report.json
                       measure real memory (daemon + browser)

  Read-only by default. To let the deck claim, ballot and post:
    export GITHUB_PAT=<fine-grained PAT: Contents read/write on the agency repos>
    agencyos run --allow-actions

  The token is read from the environment and never written to disk by Agency OS.

TXT
