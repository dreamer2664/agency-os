# Troubleshooting

Start here: `agencyos doctor` prints every dependency and source with the fix.

```
[ok  ] python          3.13.16 (>=3.10 required)
[ok  ] git             /usr/bin/git
[ok  ] ui assets       /home/you/agency-os/ui
[ok  ] data dir        /home/you/.local/share/agency-os
[ok  ] source:chatcode /home/you/.local/share/agency-os/src/chatcode @90cfff4ab4
[MISS] source:agency   /home/you/.local/share/agency-os/src/agency — run `agencyos sync`
[ok  ] token           absent — read-only mode; export GITHUB_PAT to enable private repos and writes
[ok  ] write mode      disabled (off)
[ok  ] port            0.0.0.0:8787
[ok  ] memory          1982.8 MB total, 1299.7 MB available
[ok  ] browser         /usr/bin/chromium
```

## The daemon

**`port 8787 is already in use`** — something is already listening.
`ss -ltnp | grep 8787`, then `agencyos down` or `agencyos up --port 8788`.

**`failed to start — last log lines`** — the CLI prints the tail of
`~/.agency-os/log/agencyd.log`. The usual causes are a bad `~/.config/agency-os/config.json`
(fix with `agencyos config --set …` or delete the file) and a data directory that is not writable.

**The deck says "the deck cannot see the agency"** — the browser reached the page but `/api/summary`
failed. Check `curl -s localhost:8787/api/ping`. If the daemon is down, the deck deliberately shows
nothing rather than stale numbers.

**`agencyos down` says "not running" but the port is held** — a daemon started outside the pid file
(foreground `run`, a container entrypoint). `pkill -f "agencyd.cli run"`.

## The mirrors

**`0/3 sources`, every panel empty** — `agencyos sync`. It needs `git` and network access to
`github.com`. A partial clone leaves a directory without `.git`; `rm -rf
~/.local/share/agency-os/src/<name>` and sync again.

**`sync` says `skipped: working tree is dirty`** — someone (probably you) has uncommitted changes in
a mirror. It is never discarded. Either commit them in that directory or remove the directory and
re-sync.

**Mirror is large** — mirrors are blobless + sparse (`--filter=blob:none --sparse`), so `chatcode`
costs ~5 MB rather than 105 MB. To fetch more paths, edit `sources` in the config
(`["/board/", "/agents/", …]`) and run `git -C <mirror> sparse-checkout set --no-cone …`.

**Using my own checkouts instead** — set `AGENCY_OS_CHATCODE_DIR`, `AGENCY_OS_AGENCY_DIR`,
`AGENCY_OS_STORAGECODE_DIR`. The deck then reads them directly and `sync` leaves them alone
(`git pull --ff-only` only, and only if clean).

## The deck

**Buttons say "read-only"** — that is the default. See the README's *Write access* section: token +
`--allow-actions` + agent identity.

**A panel is empty** — each empty state explains which source is missing. `agencyos sources` shows
heads and presence; `agencyos doctor` shows the same with fixes.

**"GitHub is unreachable" / "Showing a cached copy"** — anonymous API is 60 requests/hour. Wait for
the reset (the panel prints the remaining budget) or export a token. Cached data is labelled with
its error; it is never presented as live.

**Numbers look frozen** — `/api/summary` is cached per version; the version moves when a mirror
file changes. `agencyos sync` then reload the panel. In a hosted sandbox, an idle page keeps its SSE
connection and updates when something actually moves.

**Fonts look different** — the deck uses the local UI font stack (Segoe UI → system-ui → DejaVu
Sans). It never downloads a font, so a bare sandbox may render with DejaVu; layout is identical.

**Kiosk**

```bash
sudo apt-get install -y --no-install-recommends xvfb chromium
agencyos kiosk --size 1440x900            # Xvfb + Chromium single-process
agencyos kiosk --browser firefox          # heavier, but if Chromium misbehaves
```

`Xvfb :99 -screen 0 1440x900x24 &` then `DISPLAY=:99 agencyos kiosk --display :99` to use your own
X server. In a container, Chromium needs `--no-sandbox`; the kiosk script already passes it (the
page is local, static and same-origin only).

## Memory

**"It uses 400 MB"** — you are measuring the browser. `agencyos measure --kiosk` separates the two
and prints both PSS and summed RSS; `docs/MEASUREMENTS.md` has the full table and the verdict.

**Daemon above ~40 MB** — check that only one daemon is running (`ps -o pid,rss,cmd -C python3 | grep
agencyd`) and that the board data directory is not enormous (a 100 000-card board will raise cold
build time and memory; `agencyd/collect.py` caps payloads but not card count).

## Tests

**`tests/run_all.py` fails on a fresh machine** — it is offline and uses temp dirs; the usual cause
is Python < 3.10 or a `AGENCY_OS_*` variable left in the environment pointing at a real mirror.
`env | grep AGENCY_OS` then re-run with `env -u AGENCY_OS_DATA -u AGENCY_OS_HOME python3
tests/run_all.py`.
