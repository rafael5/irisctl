# irisctl

A programmer/AI-friendly CLI wrapper for InterSystems IRIS Community
Edition Docker containers. Hides the patchwork of `docker exec`,
heredocs, `iris session`, host-network helpers, license bookkeeping,
HTTP probes, and CSP page paths behind a deterministic, JSON-first
surface.

This repo implements **Phases 1, 2, and 3** of the design — read-only
floor, M/SQL execution, and source-code CRUD via Atelier.

## What's in here

```
irisctl/
├── docs/
│   ├── iris-cli-surface.md   # 531-line surface reference (what's wrapped)
│   └── iris-cli-plan.md      # 558-line proposal & implementation plan
├── src/irisctl/              # implementation
│   ├── cli.py                # argparse tree + dispatch + global flags
│   ├── output.py             # JSON envelope + human-table renderer
│   ├── http_api.py           # /api/monitor/{metrics,alerts} + Prometheus parser
│   ├── docker_api.py         # docker inspect / ports / log-tail-via-helper
│   ├── config.py             # profiles + env-var overrides + TOML
│   └── commands/             # one module per subcommand
└── tests/                    # 98 tests, ~75% coverage
```

## Install

```bash
make install     # uv sync + pre-commit hooks
```

## Use

All commands emit a versioned JSON envelope by default. Add `--human`
for a table; `--pretty` indents JSON.

```bash
$ irisctl license --human
consumed        1
available       7
cap             8
percent_used    13
days_remaining  327

$ irisctl --pretty health
{
  "v": 1,
  "ok": true,
  "command": "health",
  "data": {
    "verdict": "green",
    "checks": [
      {"name": "container_running", "ok": true},
      {"name": "listeners_all_reachable", "ok": true},
      {"name": "alerts_endpoint_reachable", "ok": true},
      {"name": "license_headroom", "ok": true, "note": "7 LUs free of 8"},
      {"name": "no_new_alerts", "ok": true, "note": "0 alert(s) since last scrape"}
    ],
    "failures": []
  },
  "warnings": []
}
```

### Phase 1 subcommands (read-only, no LU consumed)

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl license` | Current LU consumption snapshot | `/api/monitor/metrics` |
| `irisctl metrics [--prefix P]` | Filtered Prometheus counters | `/api/monitor/metrics` |
| `irisctl metrics describe NAME` | Single-counter detail | `/api/monitor/metrics` |
| `irisctl metrics scrape` | Raw Prometheus text | `/api/monitor/metrics` |
| `irisctl alerts` | System alerts since last scrape | `/api/monitor/alerts` |
| `irisctl version` | IRIS engine + image labels | `docker inspect` |
| `irisctl ports` | Per-listener reachability table | `docker inspect` + TCP probe |
| `irisctl logs [--tail N]` | Tail messages.log via root helper | `docker run alpine tail` |
| `irisctl status` | Composite container + listeners + license | aggregates the above |
| `irisctl health` | Green/yellow verdict with check breakdown | aggregates status + alerts |

### Phase 2 subcommands (1 LU per call, license-aware)

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl exec '<code>'` | Run ObjectScript via `iris session` heredoc | `docker exec -i ... iris session IRIS -U <ns>` |
| `irisctl exec --stdin` | Read script from stdin | same |
| `irisctl exec --file PATH` | Read script from a host file | same |
| `irisctl sql '<sql>'` | Run SQL, return rows as structured JSON | wraps `%SQL.Statement` |
| `irisctl sql --file PATH` | Read SQL from a host file | same |
| `irisctl shell [--ns NS]` | Interactive `iris session` proxy | `os.execvp` into `docker exec -it` |
| `irisctl shell --dry-run` | Print the docker-exec argv instead of execing | (no LU consumed) |

Phase 2 commands share three guarantees:

1. **License pre-check** — refuses near the cap (`available - 1 < reserve=1`)
   unless `--force` is given. Output: `license_exhausted` error envelope, exit code 4.
2. **HALT injection** — every script gets a trailing `HALT` if missing,
   and trailing `QUIT`/`Q` is replaced with `HALT`. Avoids the
   classic "QUIT only exits the current frame" hang.
3. **License-retry on `<LICENSE LIMIT EXCEEDED>`** — one automatic
   retry after a 1-second pause, in case the metrics endpoint hadn't
   caught up to live LU state.

Examples:

```bash
$ irisctl exec --ns %SYS 'W $ZV,!' --human
namespace  %SYS
output     IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.1 ...

$ irisctl sql --ns USER 'SELECT 1+1 AS two' --human
namespace  USER
columns    ['two']
rows       [{'two': '2'}]
rowcount   1

$ irisctl shell --dry-run --human
namespace  %SYS
argv       ['docker', 'exec', '-it', 'foia', 'iris', 'session', 'IRIS', '-U', '%SYS']
license    {'consumed': 1, 'available': 7, 'cap': 8}
```

### Phase 3 subcommands (Atelier source CRUD — auth-gated)

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl namespaces` | List IRIS namespaces + Atelier version | `GET /api/atelier/v6/` |
| `irisctl source list <NS> [pattern]` | List documents (routines + classes) | `GET /api/atelier/v6/<ns>/docnames` |
| `irisctl source get <NS> <doc>` | Read source content | `GET /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source put <NS> <doc> [--file F \| --stdin]` | Upsert a document | `PUT /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source delete <NS> <doc>` | Delete a document | `DELETE /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source compile <NS> <doc...>` | Compile listed documents | `POST /api/atelier/v6/<ns>/action/compile` |

The Atelier API is auth-gated. Credentials resolve in this order:

1. `IRISCTL_AUTH_USER` + `IRISCTL_AUTH_PW` (direct env vars).
2. `IRISCTL_AUTH_USER` + `IRISCTL_AUTH_PW_ENV` (indirection — the
   second env var names a *third* env var holding the password,
   so passwords don't appear in shell history).
3. `auth_user` / `auth_pw_env` from the active TOML profile.

When none resolve, every Phase 3 subcommand returns `auth_required`
(exit code 5). When creds resolve but IRIS rejects them, the error is
`auth_failed` (also exit code 5).

The Atelier version segment is auto-probed once per session (v6 → v1)
and cached on the client, so `source` calls don't pay the discovery
cost more than once.

Examples:

```bash
$ export IRISCTL_AUTH_USER=_SYSTEM
$ export IRISCTL_AUTH_PW='your-password-here'

$ irisctl namespaces --human
atelier_version  v6
server           IRIS for UNIX...
instance         3b6beebe6e2f
namespaces       ['%SYS', 'USER', 'VISTA', ...]

$ irisctl source list USER --human
namespace        USER
atelier_version  v6
docs             [{...}, ...]
count            42

$ echo 'myroutine ; demo' '\n' ' W "hello",!' '\n' ' Q' \
    | irisctl source put USER myroutine.mac --stdin
{"v":1,"ok":true,"command":"source","data":{"namespace":"USER","name":"myroutine.mac","lines_written":3},"warnings":[]}

$ irisctl source compile USER myroutine.mac
{"v":1,"ok":true,"command":"source","data":{"namespace":"USER","compiled":1,"flags":"ck",...},"warnings":[]}
```

### Global flags (work before *or* after the subcommand)

| Flag | Effect |
|---|---|
| `--profile NAME` | Select a profile from `~/.config/irisctl/config.toml` |
| `--json` | JSON output (default) |
| `--human` | Render as a human-readable table |
| `--pretty` | Pretty-print JSON output |

### Configuration

Default profile points at `foia` container on `localhost`.
Override via env vars (`IRISCTL_PROFILE`, `IRISCTL_CONTAINER`,
`IRISCTL_HOST`, `IRISCTL_WEB_PORT`, `IRISCTL_DATA_DIR`) or via
`~/.config/irisctl/config.toml`:

```toml
default_profile = "foia"

[profiles.foia]
container = "foia"
host = "127.0.0.1"
web_port = 52773
superserver_port = 1972
data_dir = "~/data/foia-iris"
```

## Testing approach

Per the plan: **real container only — no mocking IRIS responses.**
Every command's behavior is verified end-to-end against a live
`foia` IRIS Community container.

```bash
make test         # full suite: 98 tests, ~5 seconds
make test-unit    # parser + envelope unit tests only (no container)
make test-int    # integration tests against live foia container
make watch        # TDD mode: re-run on file save
make cov          # coverage report (target: ≥ 70%)
make check        # lint + mypy + cov (full gate)
```

The `live_iris` pytest fixture is the readiness probe — tests marked
`@pytest.mark.integration` skip cleanly if the container isn't up.

### Test totals

After Phase 3: **168 passed + 8 skipped** (~9.8s). Skipped tests are
auth-gated CRUD round-trips that need real credentials in
`IRISCTL_AUTH_USER` + `IRISCTL_AUTH_PW`.

## Output contract

Every envelope has shape:

```json
{"v": 1, "ok": true, "command": "license", "data": {...}, "warnings": []}
{"v": 1, "ok": false, "command": "exec",
 "error": {"code": "license_exhausted", "message": "...",
           "hint": "...", "ref": "..."}}
```

Stable error codes ↔ exit codes:

| Code | Exit |
|---|---|
| `ok` | 0 |
| `internal` | 1 |
| `usage` | 2 |
| `instance_not_running` | 3 |
| `license_exhausted` | 4 |
| `auth_required` / `auth_failed` | 5 |
| `not_found` | 6 |
| `iris_error` | 7 |
| `docker_error` | 8 |
| `network_error` | 9 |

## Roadmap

| Phase | Subcommands | Status |
|---|---|---|
| 1 | status, version, ports, logs, alerts, health, license, metrics | **shipped** |
| 2 | exec, sql, shell | **shipped** |
| 3 | namespaces, source list/get/put/delete/compile | **shipped** (search/diff deferred) |
| 4 | start, stop, restart, recreate, backup, restore, config show/merge | not started |
| 5 | profiles, completion, JSON-RPC mode, pip distribution | not started |

See [docs/iris-cli-plan.md](docs/iris-cli-plan.md) for the full proposal,
including the per-phase LOC estimates and the cross-tool design
contract with the parallel `ydbctl` wrapper.

## License

Internal / personal — not licensed for external use yet.
