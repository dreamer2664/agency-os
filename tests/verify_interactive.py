"""Interactive verification of the deck with a real browser (Playwright).

Checks the things a screenshot cannot: palette navigation, the task drawer, the
agent detail pane, the theme toggle, the read-only composer, and app-level errors.

    python3 tests/verify_interactive.py [--port 8787] [--shots /tmp/shots]

Exits non-zero if any check fails.  Requires playwright + a chromium build;
it is *not* part of tests/run_all.py, which must stay dependency-free.
"""
import argparse
import json
import sys

from playwright.sync_api import sync_playwright

OK, FAIL = "ok  ", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((bool(cond), name, detail))
    print(f"{OK if cond else FAIL}  {name}{('  — ' + detail) if detail else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--shots", default="/tmp/shots")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}"
    import os
    os.makedirs(a.shots, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors, console = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append((m.type, m.text)) if m.type in ("error",) else None)
        page.on("requestfailed", lambda r: console.append(("net", f"{r.url} {r.failure}")))

        page.goto(f"{base}/?boot=0", wait_until="networkidle")
        page.wait_for_timeout(1200)
        check("deck boots with zero page errors", not errors, "; ".join(errors[:3]))
        check("no console errors", not console, "; ".join(f"{t}:{m}" for t, m in console[:3]))
        check("no failed requests", not [c for c in console if c[0] == "net"])

        # masthead reflects the live agency, not a placeholder
        org = page.locator(".topbar, header").first.inner_text()
        check("masthead states the organisation status", "DORMANT" in org.upper(), org.split("\n")[0][:60])

        # ---- every rail view loads without an error state -----------------
        views = ["overview", "agents", "board", "comms", "review", "repos", "records", "resources", "settings"]
        for v in views:
            errors.clear()
            page.evaluate(f"location.hash = '#{v}'")
            page.wait_for_timeout(900)
            # only this panel's own window: the wire archive legitimately contains the
            # word "TypeError" in messages, so the whole body is the wrong thing to grep.
            win = page.locator(f'.win[data-view="{v}"]')
            text = win.inner_text() if win.count() else ""
            bad = [w for w in ("cannot reach", "failed to fetch", "cannot read this",
                               "cannot list", "is unavailable", "unexpected token")
                   if w in text.lower()]
            check(f"view '{v}' renders", win.count() > 0 and len(text) > 40 and not bad and not errors,
                  ",".join(bad) or (f"{len(text)} chars" if win.count() else "no window"))
        page.screenshot(path=f"{a.shots}/verify-settings.png")

        # ---- command palette ---------------------------------------------
        page.evaluate("location.hash = '#overview'")
        page.wait_for_timeout(400)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(500)
        pal = page.locator("#palette-input")
        check("Ctrl+K opens the palette", pal.count() == 1 and pal.is_visible())
        pal.fill("blocked")
        page.wait_for_timeout(700)
        n = page.locator("#palette-list > *").count()
        check("palette returns results for a real query", n > 0, f"{n} rows")
        page.screenshot(path=f"{a.shots}/verify-palette.png")
        pal.fill("wanderer")
        page.wait_for_timeout(700)
        check("palette searches the roster", page.locator("#palette-list > *").count() > 0)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes the palette", page.locator("#palette-input").count() == 0
              or not page.locator("#palette-input").is_visible())

        # ---- task drawer --------------------------------------------------
        page.evaluate("location.hash = '#board'")
        page.wait_for_timeout(1600)
        rows = page.locator(".grid-row")
        check("board lists cards", rows.count() > 5, f"{rows.count()} rows")
        if rows.count():
            rows.nth(2).click()
        page.wait_for_timeout(1200)
        try:
            page.wait_for_selector(".drawer:not([hidden])", timeout=4000)
        except Exception:
            pass
        drawer = page.locator(".drawer")
        open_ = drawer.count() and drawer.is_visible()
        check("clicking a card opens the drawer", open_)
        dtext = drawer.inner_text() if open_ else ""
        check("drawer shows the card id and status",
              ("CHT" in dtext or "TASK" in dtext.upper()) and len(dtext) > 80, dtext.split("\n")[0][:50])
        page.screenshot(path=f"{a.shots}/verify-drawer.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        check("Escape closes the drawer", not drawer.is_visible() if drawer.count() else True)

        # ---- agent registry detail ----------------------------------------
        page.evaluate("location.hash = '#agents'")
        page.wait_for_timeout(1400)
        agent_rows = page.locator(".split .row, .agent-row, .split [tabindex]")
        check("registry lists operatives", agent_rows.count() > 0, f"{agent_rows.count()} rows")
        if agent_rows.count():
            agent_rows.first.click()
            page.wait_for_timeout(1200)
            detail = page.locator(".col .pane-scroll").last
            dt = detail.inner_text()
            check("operative detail has an accountability verdict",
                  any(k in dt.lower() for k in ("stalled", "retired", "idle", "working", "blocked", "unknown")),
                  dt.split("\n")[0][:60])
            page.screenshot(path=f"{a.shots}/verify-agent.png")

        # ---- settings theme toggle ---------------------------------------
        page.evaluate("location.hash = '#settings'")
        page.wait_for_timeout(900)
        before = page.evaluate("document.documentElement.dataset.theme || 'graphite'")
        toggler = page.locator(".row-actions button").first
        toggler.click()
        page.wait_for_timeout(500)
        after = page.evaluate("document.documentElement.dataset.theme")
        check("theme toggle switches the deck", before != after, f"{before} -> {after}")
        page.screenshot(path=f"{a.shots}/verify-paper.png")
        toggler.click()  # leave it as we found it
        page.wait_for_timeout(300)

        # ---- composer is honest about read-only mode ----------------------
        cfg = page.evaluate("fetch('/api/config').then(r=>r.json())")
        page.evaluate("location.hash = '#comms'")
        page.wait_for_timeout(1200)
        ta = page.locator("#composer-text")
        disabled = ta.count() > 0 and ta.first.is_disabled()
        check("composer is disabled while write mode is off",
              disabled == (not cfg.get("actions_enabled")),
              f"actions_enabled={cfg.get('actions_enabled')} disabled={disabled}")
        if disabled:
            note = " ".join(page.locator(".composer-note").all_inner_texts())
            check("composer explains how to enable posting",
                  "allow-actions" in note.lower() and "token" in note.lower(), note[:90])

        # ---- write endpoint refuses without write mode --------------------
        status = page.evaluate("""async () => {
            const r = await fetch('/api/action', {method:'POST',
                headers:{'Content-Type':'application/json','X-AgencyOS':'1'},
                body: JSON.stringify({verb:'say', text:'probe'})});
            return r.status;
        }""")
        check("POST /api/action is refused when not armed", status in (403, 409), f"HTTP {status}")

        # ---- SSE keeps the deck live --------------------------------------
        feed = page.evaluate("""async () => {
            const seen = [];
            await new Promise((res) => {
                const es = new EventSource('/api/events');
                const grab = (e) => { seen.push(e.type + ":" + e.data.slice(0, 30)); es.close(); res(); };
                es.addEventListener("hello", grab);
                es.addEventListener("change", grab);
                setTimeout(() => { es.close(); res(); }, 4000);
            });
            return seen;
        }""")
        check("SSE greets the deck with a hello", len(feed) > 0, feed[0] if feed else "no event in 4 s")

        check("still no page errors after interaction", not errors, "; ".join(errors[:3]))
        browser.close()

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
