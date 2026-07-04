---
# Machine-readable project descriptor — schema v1 (2026-05-05).
name: irisctl
kind: [cli, tool]
status: archived                           # retired 2026-07-04 — superseded by vista-forge m-iris/irissync over m-driver-sdk
languages: [python]

runtime:
  needs:
    - python>=3.10
    - docker
    - "running InterSystems IRIS Community container (test target: `foia` at ~/data/foia-iris/)"
  optional: []
  excludes:
    - "yottadb (use ydbctl sibling instead)"
    - "windows (untested; assumes Linux docker)"

distribution:
  pypi: null                               # pipx skipped per Rafael 2026-05-03
  github: rafael5/irisctl                  # private

location: ~/projects/irisctl

exposes:
  cli:
    - irisctl                              # ~30 subcommands; JSON-first output for AI agents
  capabilities:
    - "wraps `docker exec` + heredocs + `iris session` + host-network helpers"
    - "license bookkeeping, HTTP probes, CSP page paths"
    - "JSON-RPC mode for AI agents"
  ports_known:
    - "1972 superserver"
    - "52773 web gateway / Mgmt Portal / /api/monitor/metrics (unauth)"
    - "9430 RPC Broker"
    - "8001 VistALink"

consumes:
  formats: []
  services: ["docker daemon", "running IRIS container"]

companions:
  - project: ydbctl
    relation: "sibling — same envelope shape and overlapping subcommands for the YottaDB Docker side"
  - project: docker-vista-fork
    relation: "irisctl wraps containers built from docker-vista-fork's Dockerfile (IRIS path)"
  - project: fm-web
    relation: "fm-web targets the IRIS-backed VistA exposed via irisctl-managed containers"

incompatibilities:
  - "IRIS-specific. YDB containers use ydbctl; the two CLIs deliberately don't overlap on backend-specific commands."
  - "Tests require a live `foia` container — no IRIS response mocking by design."

docs:
  primary: README.md
  surface: docs/iris-cli-surface.md
  plan: docs/iris-cli-plan.md
---

# irisctl — Claude Project Context

## What this project is

A programmer/AI-friendly CLI wrapper for InterSystems IRIS Community
Edition Docker containers. Hides the patchwork of `docker exec`,
heredocs, `iris session`, host-network helpers, license bookkeeping,
HTTP probes, and CSP page paths behind a deterministic, JSON-first
surface.

Companion documents in `docs/`:
- `iris-cli-surface.md` — the surface this wraps
- `iris-cli-plan.md` — the proposal & implementation plan (5 phases)

## Test target — the live foia container

**Every command is tested against a real IRIS container** named `foia`
running on `localhost`. Per the project plan, "real container only —
no mocking IRIS responses."

Tests are marked `integration` if they need the live container; run
just those with `make test-int`. Unit tests (parsers, output
formatting) run via `make test-unit` without container deps.

The container exposes:
- 1972 — superserver
- 52773 — Web Gateway / Mgmt Portal / `/api/monitor/metrics` (unauth)
- 9430 — RPC Broker
- 8001 — VistALink

Probe with: `docker run --rm --network host alpine sh -c \
'wget -qO- http://localhost:52773/api/monitor/metrics' | head`

## Dev workflow

```bash
make install      # create .venv, install deps + pre-commit hooks
make test         # all tests (integration + unit)
make test-unit    # parser/output tests only — no container needed
make test-int     # integration tests against live foia container
make watch        # TDD mode: auto-rerun on file save
make cov          # pytest with coverage report
make check        # lint + mypy + cov (full gate)
make format       # ruff format
make push         # check + git push
```

## Architecture (per [docs/iris-cli-plan.md](docs/iris-cli-plan.md) §6)

```
src/irisctl/
├── cli.py              # argparse tree + dispatch
├── config.py           # profiles, env, defaults
├── output.py           # JSON envelope, human renderer
├── http_api.py         # /api/monitor/* wrappers
├── docker_api.py       # docker inspect / exec / start / stop
├── exec_session.py     # iris session heredoc with HALT injection
├── license.py          # LU pre-check helper
└── commands/
    ├── status.py
    ├── version.py
    ├── ports.py
    ├── logs.py
    ├── alerts.py
    ├── health.py
    ├── license.py
    └── metrics.py
```

## Output contract (per plan §4)

Every command emits the same JSON envelope (or pretty table with
`--human`):

```json
{"v": 1, "ok": true, "command": "license", "data": {...}}
{"v": 1, "ok": false, "command": "exec",
 "error": {"code": "license_exhausted", "message": "...",
           "hint": "...", "ref": "iris-cli-surface.md#10-gotchas"}}
```

Exit codes: 0=ok, 1=internal, 2=usage, 3=instance_not_running,
4=license_exhausted, 5=auth_required/auth_failed, 6=not_found,
7=iris_error, 8=docker_error, 9=network_error.

## Phasing

This codebase implements **Phase 1** of the plan: read-only floor
(no LU consumption, no auth required).

| Phase | Subcommands | Status |
|---|---|---|
| 1 | status, version, ports, logs, alerts, health, license [watch], metrics [describe \| scrape] | **in progress** |
| 2 | exec, sql, shell | not started |
| 3 | source list/get/put/delete/compile/search/diff, namespaces | not started |
| 4 | start, stop, restart, recreate, backup, restore, config show/merge | not started |
| 5 | profiles, completion, JSON-RPC mode, pip distribution | not started |

## Code style

- TDD — write tests first
- Ruff for format + lint (no black)
- Line length 88
- Logging not print() in library code
- No mocks unless unavoidable (per `~/.claude/CLAUDE.md`)
- Hobbyist project — keep solutions simple and direct
- Edit existing files in preference to creating new ones
