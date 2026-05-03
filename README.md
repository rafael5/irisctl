# irisctl

A programmer/AI-friendly CLI wrapper for InterSystems IRIS Community
Edition Docker containers. Hides the patchwork of `docker exec`,
heredocs, `iris session`, host-network helpers, license bookkeeping,
HTTP probes, and CSP page paths behind a deterministic, JSON-first
surface.

This repo implements **Phases 1–5** of the design — read-only
floor, M/SQL execution, source-code CRUD via Atelier, lifecycle +
persistence, and convenience + JSON-RPC mode for AI agents.

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

### Phase 4 subcommands (lifecycle + persistence — mutating)

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl start` | Start the container; wait for listeners | `docker start` + TCP probe |
| `irisctl stop [--timeout 60]` | Graceful shutdown | `docker stop -t N` |
| `irisctl restart` | Stop + start | composite |
| `irisctl recreate --image I --yes` | Remove + run from host volume (destructive) | `docker rm` + `docker run` per [INSTALL_GUIDE](docs/iris-cli-surface.md) §8 |
| `irisctl backup [--to PATH] [--offline]` | Tar host volume to a backup tarball | helper `alpine tar` |
| `irisctl restore --from PATH --yes` | Replace host volume from tarball (destructive) | helper `alpine` wipe + untar |
| `irisctl config show` | Read iris.cpf via host bind-mount | helper `alpine cat` |
| `irisctl config merge FILE` | Apply CPF fragment via `iris merge` | `docker cp` + `docker exec iris merge` |

Safety guardrails:

- **`recreate` and `restore` require `--yes`** — they wipe Docker
  state. Both also accept `--dry-run` to print the planned argv/steps.
- **`backup` defaults to `--online`** (live tar, faster); pass
  `--offline` for stop+tar+start consistency.
- **`config merge` is the only safe CPF mutation path.** Direct edits
  to a running `iris.cpf` get overwritten on shutdown.

Full container cycles (real stop+start, real backup) are gated behind
`@pytest.mark.slow` so default `make test` stays under 12s. Run them
explicitly with `make test-slow` (~60-180s).

Examples:

```bash
$ irisctl start --human
container        foia
already_running  yes
listeners        {1972: True, 52773: True, 9430: True, 8001: True}

$ irisctl config show --human | head -3
path        /home/rafael/data/foia-iris/iris.cpf
size_bytes  14135
text        [ConfigFile]Product=IRIS...

$ irisctl backup --to /tmp/snap.tgz --dry-run --human
path     /tmp/snap.tgz
online   yes
dry_run  yes
steps    ['# online=True; out=/tmp/snap.tgz', ..., 'docker run --rm --user 0 -v ... alpine tar czf ...']

$ irisctl recreate --dry-run
{"v":1,"ok":true,"command":"recreate","data":{"argv":["docker","run","--name","foia","-d","-v","/home/rafael/data/foia-iris/mgr:/usr/irissys/mgr",...]}}
```

### Phase 5 subcommands (convenience + AI-friendly modes)

| Command | Purpose | Notes |
|---|---|---|
| `irisctl which [OP]` | Explain the underlying docker / HTTP / iris-session command for any op | Debug + discovery aid; lists all if no OP |
| `irisctl portal [PATH]` | Open Mgmt Portal in the default browser (`/csp/sys/PATH`) | `--dry-run` prints the URL |
| `irisctl docs KEY` | Open InterSystems docs page for KEY (e.g. `ADOCK`, `GCM_rest`) | `--dry-run` prints the URL |
| `irisctl rpc` | JSON-RPC 2.0 server on stdin/stdout | One persistent process for AI agents |
| `irisctl status --watch [--interval N]` | Repoll status until interrupted | Default 5s; Ctrl-C exits cleanly |
| `irisctl license --watch [--interval N]` | Repoll license until interrupted | Default 5s |
| Shell completion | argcomplete-driven bash/zsh/fish | `eval "$(register-python-argcomplete irisctl)"` |

### JSON-RPC mode for AI agents

`irisctl rpc` is the load-bearing Phase 5 feature for AI use. Instead
of spawning ~28 distinct CLI processes (each paying argparse +
config-load startup cost), an agent pipes newline-delimited JSON-RPC
2.0 requests in and reads responses out:

```bash
$ printf '%s\n%s\n' \
    '{"jsonrpc":"2.0","method":"license","id":1}' \
    '{"jsonrpc":"2.0","method":"which","params":{"op":"exec"},"id":2}' \
  | irisctl rpc
{"jsonrpc":"2.0","id":1,"result":{"v":1,"ok":true,"command":"license","data":{"consumed":1,"available":7,"cap":8,"percent_used":13,"days_remaining":327},"warnings":[]}}
{"jsonrpc":"2.0","id":2,"result":{"v":1,"ok":true,"command":"which","data":{"op":"exec","mechanism":"docker exec -i + iris session heredoc (HALT-injected)","underlying":"docker exec -i foia iris session IRIS -U <ns> ...","lu_cost":1},"warnings":[]}}
```

All Phase 1–5 commands are exposed as RPC methods (~30 total) — see
the registry in [src/irisctl/rpc.py](src/irisctl/rpc.py) `METHODS`.
Standard JSON-RPC 2.0 error codes apply: `-32700` parse error,
`-32600` invalid request, `-32601` method not found, `-32602` invalid
params, `-32603` internal error. Notifications (no `id`) get no
response. The body of every successful `result` is the same JSON
envelope produced by the corresponding CLI subcommand.

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

After Phase 5: **233 passed + 8 skipped + 3 deselected** (~12s).

- 8 skipped: auth-gated Atelier CRUD round-trips waiting on
  `IRISCTL_AUTH_USER` + `IRISCTL_AUTH_PW`.
- 3 deselected: full container stop+start+restore cycles (`@slow`).
  Run with `make test-slow` (~60-180s).

Default coverage gate: 60% (slow tests would push it past 80%).

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
| 4 | start, stop, restart, recreate, backup, restore, config show/merge | **shipped** |
| 5 | which, portal, docs, --watch, JSON-RPC, shell completion | **shipped** (pipx packaging skipped) |

See [docs/iris-cli-plan.md](docs/iris-cli-plan.md) for the full proposal,
including the per-phase LOC estimates and the cross-tool design
contract with the parallel `ydbctl` wrapper.

## License

Internal / personal — not licensed for external use yet.
