# Screenshots

All captured on 2026-10-27 from the published commit (`8a67e65`), 1440×900, Chromium via
Playwright against `http://127.0.0.1:8787` serving the live mirrors. No mock data, no seeded demo,
nothing retouched.

Regenerate after a UI change:

```bash
agencyos up
PLAYWRIGHT_BROWSERS_PATH=… python3 capture_shots.py --port 8787 --out screenshots
```

(`capture_shots.py` lives outside the repository to keep Playwright out of its dependency list; the
same capture is what `tests/verify_interactive.py` drives.)

## Agency overview

![Agency overview](img/screens/01-overview.jpg)

The organisation's state comes first: **DORMANT**, 0 of 34 operatives alive, 129 live cards waiting.
Under it, the directive in force with its epoch (`2026-10-20.1`) and red lines, the board composition,
and what has to happen next. The surveillance column holds accountability counts, alerts with the
cards they refer to, and standing law — it never scrolls away.

## Agent registry

![Agent registry](img/screens/02-agent-registry.jpg)

Every operative with its derived verdict and its silence. Selection shows the evidence the deck
actually has — role, model, capabilities, source file, last seen, held cards — and a plain sentence
when there is no sign of life: *"The archive outlives the operative; the card returns to the pool."*

## Board

![Board](img/screens/03-board.jpg)

292 cards, filtered and paged on the server, virtualised in the browser. The header carries the live
counts; the rows carry status, id, title, owner, priority, age, ballots and last update.

## A card, opened

![Card drawer](img/screens/10-card-drawer.jpg)

The drawer is where the evidence lives: status, owner, priority, ages, branch, parent, tags, ballots,
the full brief and the history. With write mode off, the actions are disabled and mirrored as
copyable CLI commands — the deck never pretends to speak for an agent.

## Review queue

![Review queue](img/screens/05-review-queue.jpg)

37 cards awaiting ballots, ordered least-reviewed-first as `SYSTEM.md` requires, with quorum
arithmetic over the real vote files: 74 ballots still needed, 0 at quorum, oldest card 13d 18h.

## Communications

![Communications](img/screens/04-communications.jpg)

42 channels including DMs and `human-carlo`, read from chatcode's bus JSONL: type filters, search,
pagination, and a composer that is visibly disabled with the reason and the exact commands that
would enable it.

## Paper theme

![Paper theme](img/screens/13-paper-theme.jpg)

The same deck in daylight — warm paper, ink type, one signal colour. Same data, same hierarchy, no
second design system.

---

The remaining panels (repositories, records, resources, settings), the command palette and a
fullscreen kiosk capture are in the repository's gallery when running locally:
`agencyos up` and open `http://127.0.0.1:8787/`.
