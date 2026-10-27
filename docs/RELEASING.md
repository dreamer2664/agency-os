# Releasing

Versions are semantic and live in `VERSION` (single source; `agencyd/config.py` reads it and the CLI
prints it). `CHANGELOG.md` accumulates under `## [Unreleased]`.

1. **Green gate**

   ```bash
   python3 tests/run_all.py                # 15/15
   bash -n scripts/*.sh
   for f in ui/js/*.js ui/js/views/*.js; do node --input-type=module --check < "$f"; done
   scripts/measure.sh --kiosk --seconds 15 # append the row to docs/MEASUREMENTS.md
   ```

2. **Version**

   ```bash
   echo "0.2.0" > VERSION
   # CHANGELOG.md: move Unreleased items under "## [0.2.0] — YYYY-MM-DD"
   ```

3. **Commit and tag**

   ```bash
   git add -A && git commit -m "release: 0.2.0"
   git tag -a v0.2.0 -m "Agency OS 0.2.0"
   git push origin main --follow-tags
   ```

4. **Publish** GitHub release from the tag; body = the changelog section. Nothing is uploaded as a
   binary: the repository *is* the distribution, `scripts/install.sh` is the installer, and
   `git pull --ff-only && ./scripts/install.sh` is the update path.

5. **Verify from a clean directory** (this is the step that catches a broken installer):

   ```bash
   cd /tmp && rm -rf verify && git clone https://github.com/dreamer2664/agency-os verify
   cd verify && ./scripts/install.sh --no-browser && agencyos up && agencyos status && agencyos down
   ```
