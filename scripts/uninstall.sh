#!/usr/bin/env bash
# Agency OS — uninstaller. Removes the runtime state Agency OS created.
# It never deletes a source checkout and never touches your repositories.
#
#   ./scripts/uninstall.sh             remove mirrors, cache, logs, config, command
#   ./scripts/uninstall.sh --keep-data keep mirrors and cache (~20 MB) for a fast reinstall
set -uo pipefail
KEEP_DATA=0
for arg in "$@"; do
  case "$arg" in
    --keep-data) KEEP_DATA=1 ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[38;5;179m▸\033[0m %s\n' "$*"; }

# stop the daemon if it is running
if command -v agencyos >/dev/null 2>&1; then
  say "stopping the daemon"
  agencyos down || true
fi
for pidfile in "$HOME/.agency-os/run/agencyd.pid"; do
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile" 2>/dev/null || true)
    [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null || true
    rm -f "$pidfile"
  fi
done

say "removing the command"
rm -f "$HOME/.local/bin/agencyos"

say "removing configuration"
rm -rf "$HOME/.config/agency-os"

say "removing logs"
rm -rf "$HOME/.agency-os"

if [ "$KEEP_DATA" = "1" ]; then
  say "keeping mirrors and cache in $HOME/.local/share/agency-os"
else
  say "removing mirrors and cache"
  rm -rf "$HOME/.local/share/agency-os"
fi

echo
echo "Agency OS removed. Your source checkout (this directory) is untouched."
