# Roadmap / what is not finished

Honest list as of 0.1.0.

## Not built

1. **The 300 MB target with a full browser.** Closest is 326 MB median (Chromium `--single-process`
   kiosk). Closing it needs either a lighter browser engine or a browser-free client. A TUI client
   sharing `agencyd`'s API would land near 30 MB total and is the obvious next experiment; it is
   not built because it abandons the visual identity this project exists for.
2. **Manager workflow beyond claims and ballots.** The deck can claim, heartbeat, release, ballot
   and post; it cannot create tasks or job briefs. Those are `chatcode tasks new` / brief authoring
   by a manager. A guided "cut a card" form with the brief template is the next real feature.
3. **Multi-repository job views from `chatcode/projects/`.** The board is read; the per-project
   briefs under `projects/` are not yet surfaced.
4. **Deployment beyond a sandbox.** No systemd unit, no container image. `agencyos up` +
   `scripts/kiosk.sh` cover a single machine; packaging is left to whoever needs it.
5. **Notification channel.** The wire is read, not subscribed; there is no desktop notification when
   a card enters review. An SSE-fed toast exists in the deck, but nothing rings outside the browser.
6. **Timeline retention controls.** The activity view reads the last 13 days of the wire; there is
   no archival view for older events (the file itself is the archive).

## Deliberately not building

* A second bus, a second ledger, or a second board — the repositories are the system.
* An agent runtime. Agency OS observes and, in write mode, delegates; it never *runs* agents.
* A generic desktop environment, application launcher, or file manager.

## Ideas worth testing first

* WebKitGTK with tuned `WebKitSettings` (memory) as the kiosk engine — surf measured 381 MB
  multi-process, which suggests the single-process ceiling is lower than Chromium's.
* Serving the deck from a tiny native HTTP server and keeping the UI — the daemon's 25 MB would drop
  further, but it is already 8 % of budget, so the win is cosmetic.
* Reading `chatcode/projects/*/JOBS.md` to give each project a progress panel.
