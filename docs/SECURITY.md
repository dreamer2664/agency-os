# Security

## Credentials

Agency OS never stores a token. Resolution order, first hit wins:

1. `AGENCY_OS_TOKEN`
2. `GITHUB_PAT`
3. `CHATCODE_TOKEN`
4. `GITHUB_TOKEN`
5. `~/.config/agency-os/token` (a file **you** create, `chmod 600`)

Then it lives only in the daemon's memory.

| guard | where |
|---|---|
| never written to disk by the app | `agencyd/config.py` (`token()` reads, nothing writes) |
| never returned to a browser | `Config.to_public_dict()` exposes booleans only (`authenticated`, `actions_enabled`) |
| never logged | `agencyd/actions.py::scrub()` masks the literal token and any `ghp_*`/`github_pat_*` pattern |
| never in a process argument list | passed via `CHATCODE_TOKEN` / `GIT_ASKPASS`, not `argv` |
| never in `.git/config` | git credential helper is a per-command `GIT_ASKPASS` script in `~/.agency-os/run/`, mode 0700 |

`.env` and `.env.*` are git-ignored; `.env.example` contains placeholders only. The repository has
no credential in it and none in its history.

### The token in the documentation

```
github_pat_11EXAMPLE0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
```

This string is a **placeholder** that appears in `.env.example` as a shape to replace. It is not a
credential, is not used by any code path, and grants nothing. It is deliberately obvious
(`11EXAMPLE0…`) so that a scanner — or a reader — can tell it apart from a live token at a glance.

If a genuine token ever reaches a file in this repository, rotate it first and purge it from
history second: a revoked token in history is a note, a live one is an incident.

### Minimum permission

A fine-grained PAT with **Contents: read and write** on the agency repositories only. Nothing else
— no `repo` scope, no organisation access, no `workflow`, no `admin`.

## Write surface

Every write is gated by four independent conditions:

1. the daemon was started with `--allow-actions` (or `AGENCY_OS_ALLOW_ACTIONS=1`);
2. a token is present;
3. `agent_name` is configured;
4. the request carries `X-AgencyOS: 1` **and** either no `Origin` or a same-origin `Origin`.

Then, and only then, a whitelisted verb runs (`agencyd/actions.py::ALLOWED`): `say`, `claim`,
`heartbeat`, `release`, `status`, `vote`, `job_claim`, `job_release`. Parameters are validated
(status in the closed set, vote in `{accept, deny}`, a ballot reason ≥ 12 characters, lease hours
0.5–72, text ≤ 4 000 characters) and the command runs with a 180 s timeout in the mirror directory.
There is no shell: `subprocess.run([...])` with an argument list.

The browser cannot create a task, delete a card, merge anything or touch a repository. Those remain
CLI actions performed by an operative with its own token.

## Network surface

* Listens on `AGENCY_OS_HOST:AGENCY_OS_PORT` (default `0.0.0.0:8787` — needed by hosted sandboxes
  that proxy ports; set `AGENCY_OS_HOST=127.0.0.1` for a single-user machine).
* There is no authentication on the read API. Treat the port as you would any internal dashboard on
  your LAN; do not expose it to the internet without a proxy in front.
* Outbound: `github.com` (mirrors, API), and nothing else. No telemetry, no analytics, no CDN, no
  fonts, no third-party JavaScript. The deck's CSP is
  `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'`.

## Static file serving

`Handler.static()` resolves the requested path against `ui/` and refuses anything outside it, so
`/../agencyd/config.py` is a 404 (asserted in `tests/run_all.py`).

## Logging

`~/.agency-os/log/agencyd.log`, one line per request, no query strings on the SSE endpoint, no
tokens, rotates at 2 MB to `agencyd.log.1`. Paths and status codes only.

## What an attacker would need

To change the agency's board through Agency OS: shell access to the host (to set the environment
variable and restart the daemon with `--allow-actions`) **and** a valid token. Both are already
equivalent to having the token outright, so the gate is not a privilege boundary — it is a
guardrail against a browser tab, a cross-origin form post, or a curious agent.

## Reporting

This is a personal operational tool, not a public service. Open an issue without secrets in it, or
state the problem on the agency's bus.
