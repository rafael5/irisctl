# `irisctl` — Proposal & Implementation Plan

A unified CLI wrapper that hides the patchwork of `docker exec`,
heredocs, `iris session`, host-network helpers, license bookkeeping,
HTTP probes, and CSP page paths behind one deterministic, JSON-first
surface — designed so an AI agent can drive an IRIS Community Edition
instance without re-discovering [the surface](iris-cli-surface.md) on
every task.

This is a proposal, not an implementation. Companion document:
[iris-cli-surface.md](iris-cli-surface.md) — the surface this wraps.

---

## 1. Goal

When an AI agent (or a programmer) asks "is the license OK", "what
namespaces exist", "compile this routine", "tail the log", or "give me
a SQL prompt", the path to an answer should be a single subcommand —
not a per-task decision tree about which of `docker exec`,
`iris session`, `/api/atelier/v6`, `/csp/sys/...`, or
`alpine --network host` to use.

**Concrete pain the wrapper fixes:**

| Today | With `irisctl` |
|---|---|
| `docker exec -i foia iris session IRIS -U %SYS <<'END' … HALT END` plus remembering `HALT` not `QUIT` | `irisctl exec --ns %SYS '…'` |
| `docker run --rm --network host alpine sh -c 'wget -qO- http://localhost:52773/api/monitor/metrics' \| awk …` | `irisctl license` / `irisctl metrics` |
| Editing `iris.cpf` by hand, breaking on next shutdown | `irisctl config merge file.cpf` |
| `docker run --rm --user 0 -v ~/data/foia-iris:/data:ro alpine tail …` | `irisctl logs --tail 200` |
| Discovering which of `/api/atelier/v1`…`/v6` works | `irisctl source list NS` (probes once, caches version) |
| Forgetting that `iris session` consumes 1 LU per call | `irisctl exec` checks LUs first; refuses near cap |

---

## 2. Design principles

1. **One tool, one binary, no plugins.** The whole surface lives under
   `irisctl <verb> [args]`. Sub-verbs nest one level deep
   (`source list`, `license watch`).
2. **JSON-first output.** Default stdout is a structured envelope.
   `--human` flag switches to a pretty table for terminal use.
   Schema is versioned (`"v": 1`) so AI consumers can detect breakage.
3. **Idempotent where possible.** `restart` is `stop+start` not a
   third state. `source put` is upsert. Repeating a command should
   not produce a different result given the same instance state.
4. **HTTP-first, container-second, exec-last.** Every operation
   prefers the cheapest path:
   - **No-LU path:** `/api/monitor/*`, `docker inspect`, host
     filesystem reads via root-helper container.
   - **Cheap-LU path:** `/api/atelier/*` (1 LU per request, but auth
     handled, retry-safe).
   - **Expensive path:** `iris session` heredoc (1 LU, blocks until
     exit, easy to leak).
   The wrapper picks automatically; users can force a path with
   `--via=http|atelier|exec`.
5. **License-aware.** Before any LU-consuming subcommand the wrapper
   reads `/api/monitor/metrics`, refuses if `iris_license_consumed >=
   cap - reserve` (default `reserve=1`), and emits a structured
   error. `--force` bypasses.
6. **Stateless by default.** No long-running daemon. State lives in
   the IRIS instance and an optional config file. `--watch` sub-modes
   poll, they don't subscribe.
7. **Single-instance assumption, multi-instance ready.** Default
   target is `foia`. A `--profile` flag (and `IRISCTL_PROFILE` env)
   selects from `~/.config/irisctl/config.toml`.
8. **Unsurprising error envelope.** Every error has a stable code, a
   human message, and a hint pointing at the surface doc section.

---

## 3. Subcommand inventory

Grouped by mechanism. Every subcommand emits the standard JSON
envelope (§4) unless `--human` is given.

### 3.1 Inspection / health (no-LU, HTTP + docker inspect)

| Subcommand | Wraps | Why it exists |
|---|---|---|
| `irisctl status` | `docker inspect` + port probe + `/api/monitor/metrics` `iris_system_state` | "Is everything OK in one shot." Returns container state, listener-port reachability, system_state, license headroom. |
| `irisctl version` | image labels (`com.intersystems.platform-version`) + `iris_system_info` metric | IRIS build, image build date, instance name. |
| `irisctl ports` | `docker inspect` + TCP probe via host-network helper | Per-port state: `listening`/`closed`, mapped host port, role. |
| `irisctl logs [--tail N] [--follow]` | root-helper `tail` of `mgr/messages.log` | No `docker exec`. `--follow` streams. |
| `irisctl alerts` | `/api/monitor/alerts` | All `alerts.log` entries since last call as JSON. |
| `irisctl health` | runs `status` + `ports` + `alerts` + healthcheck script | Composite "should I worry" check. Exits non-zero if anything red. |

### 3.2 License (no-LU, HTTP)

| Subcommand | Wraps |
|---|---|
| `irisctl license` | `/api/monitor/metrics` `iris_license_*` — current snapshot. Replaces `~/scripts/bin/foia-license`. |
| `irisctl license watch [--interval Ns]` | Poll loop. Default 5s. |
| `irisctl license users` | `/csp/sys/op/UtilSysLicenseUse.csp` scrape, or `^%SYS.LICENSE` ObjectScript fallback. Lists which users/processes are holding LUs right now. |

### 3.3 Metrics (no-LU, HTTP)

| Subcommand | Wraps |
|---|---|
| `irisctl metrics [--prefix iris_db_]` | `/api/monitor/metrics` filtered. JSON list of `{name,help,type,labels,value}`. |
| `irisctl metrics describe NAME` | Single counter with HELP/TYPE/value. |
| `irisctl metrics scrape` | Raw Prometheus text (for piping to monitoring tools). |

### 3.4 Source code CRUD (1 LU per call, `/api/atelier`)

| Subcommand | Wraps |
|---|---|
| `irisctl source list <NS> [PATTERN]` | `GetDocNames` |
| `irisctl source get <NS>/<doc>` | `GetDoc` (writes content to stdout; metadata to stderr if `--meta`) |
| `irisctl source put <NS>/<doc>` (stdin) | `PutDoc` (upsert) |
| `irisctl source delete <NS>/<doc>` | `DeleteDoc` |
| `irisctl source compile <NS> <PATTERN>` | `Compile` (returns errors as structured JSON) |
| `irisctl source search <NS> <PATTERN>` | `Search` (full-text) |
| `irisctl source diff <NS>/<doc> <file>` | local convenience: `GetDoc` + `diff` |

### 3.5 Execution (1 LU per call, `iris session`)

| Subcommand | Wraps |
|---|---|
| `irisctl exec [--ns NS] '<objectscript>'` | `iris session IRIS -U NS '<cmd>'`. Auto-appends `HALT`. License-pre-check. |
| `irisctl exec --ns NS --stdin` | heredoc from stdin. Auto-prepends `ZN` if `--ns` given. |
| `irisctl exec --ns NS --file routine.m` | copies into `/tmp`, loads, runs main entry, returns output. |
| `irisctl sql [--ns NS] '<statement>'` | `runsql`-equivalent. JSON result-set: `{columns, rows, rowcount, error}`. |
| `irisctl sql --ns NS --file schema.sql` | DDL import via `$SYSTEM.SQL.Schema.ImportDDL`. |
| `irisctl shell [--ns NS]` | interactive `iris terminal` proxy. Warns if license is low. **Honestly just `docker exec -it`** with a license check — but provides the same UX as the rest. |

### 3.6 Namespaces & databases (no-LU, HTTP)

| Subcommand | Wraps |
|---|---|
| `irisctl namespaces` | `/api/atelier/v6/` server info → namespaces array. |
| `irisctl databases [NS]` | `iris_db_*` metrics + `/api/atelier` namespace info. Per-DB size, free space, file limit pct. |

### 3.7 Lifecycle (mutating, container-level)

| Subcommand | Wraps |
|---|---|
| `irisctl start` | `docker start foia` (or `docker run` if not present, using config). Waits for listeners. |
| `irisctl stop [--timeout 60]` | `docker stop -t N foia`. Default 60s (the 10s default is too short). |
| `irisctl restart` | stop + start. |
| `irisctl recreate` | `docker rm -f` + `docker run` per [the documented restore recipe](INSTALL_GUIDE.md#8-restoring-after-teardown). |

### 3.8 Persistence (mutating)

| Subcommand | Wraps |
|---|---|
| `irisctl backup [--to PATH]` | stop → tar `~/data/foia-iris/` via root helper → start. Default path `~/data/backups/foia-iris-<UTC>.tgz`. |
| `irisctl restore --from PATH` | stop → wipe `~/data/foia-iris/` → untar → start. Confirmation prompt unless `--yes`. |
| `irisctl config show` | dump current `iris.cpf` (read via root helper). |
| `irisctl config merge <file>` | `iris merge IRIS <file> /usr/irissys/iris.cpf` — the only safe CPF mutation path. |

### 3.9 Convenience

| Subcommand | Wraps |
|---|---|
| `irisctl portal [PATH]` | open `xdg-open http://localhost:52773/csp/sys/PATH` (defaults to `UtilHome.csp`). |
| `irisctl docs <KEY>` | open `https://docs.intersystems.com/...?KEY=KEY` in browser. |
| `irisctl which <op>` | meta — print the *underlying* command/path for an op (debug aid for users). |

---

## 4. Output contract

### 4.1 Success envelope

```json
{
  "v": 1,
  "ok": true,
  "command": "license",
  "data": {
    "consumed": 1,
    "available": 7,
    "cap": 8,
    "percent_used": 13,
    "days_remaining": 327
  }
}
```

### 4.2 Error envelope

```json
{
  "v": 1,
  "ok": false,
  "command": "exec",
  "error": {
    "code": "license_exhausted",
    "message": "Cannot run exec: 8/8 LUs consumed",
    "hint": "irisctl license users  # see who is holding LUs",
    "ref": "iris-cli-surface.md#10-gotchas"
  }
}
```

### 4.3 Stable error codes

| Code | Meaning | Exit |
|---|---|---|
| `ok` | success | 0 |
| `usage` | invalid arguments | 2 |
| `instance_not_running` | container is stopped/missing | 3 |
| `license_exhausted` | LUs at/above threshold | 4 |
| `auth_required` | endpoint returned 401 and no creds configured | 5 |
| `auth_failed` | creds rejected | 5 |
| `not_found` | namespace/document/metric missing | 6 |
| `iris_error` | underlying IRIS error | 7 |
| `docker_error` | container-level failure | 8 |
| `network_error` | port unreachable / HTTP failed | 9 |
| `internal` | wrapper bug | 1 |

### 4.4 Human mode (`--human`)

Tables for list-ish output, key:value blocks for record-ish output.
ANSI color in TTYs only. Always falls back to plain text when piped.

---

## 5. Configuration

### 5.1 Config file

`~/.config/irisctl/config.toml`:

```toml
default_profile = "foia"

[profiles.foia]
container = "foia"                              # docker name
host = "127.0.0.1"
superserver_port = 1972
web_port = 52773
data_dir = "~/data/foia-iris"
license_reserve = 1                              # refuse LU ops below this many free
auth_user = "_SYSTEM"
auth_pw_env = "IRISCTL_FOIA_PW"                  # read pw from env var (not the file)

[profiles.foia.atelier]
version = "auto"                                 # "auto" probes v6→v5→…→v1
```

### 5.2 Env var overrides

`IRISCTL_PROFILE`, `IRISCTL_HOST`, `IRISCTL_WEB_PORT`,
`IRISCTL_USER`, `IRISCTL_PW`, `IRISCTL_NO_LICENSE_CHECK`,
`IRISCTL_OUTPUT=json|human|prom`.

### 5.3 No creds in config file

Passwords are read from env vars referenced by `auth_pw_env`, never
stored in the TOML. For interactive use, prompt and stash in the
session via `keyring` if available.

---

## 6. Implementation strategy

### 6.1 Language: Python (with `uv`)

**Why Python:**
- Surface is ~30 subcommands × multiple modes. Bash quickly stops
  scaling past ~500 LOC of nested case statements.
- `requests` / `httpx` for HTTP, `tomllib` (stdlib 3.11+) for config,
  `argparse` (or `click`) for the CLI tree, `pydantic` (optional) for
  schemas. All standard.
- Matches Rafael's default Python toolchain (`uv`, `ruff`, `mypy`,
  `pytest` per `~/.claude/CLAUDE.md`).
- Easy to package as a single-file zipapp or via PyInstaller for
  distribution to other machines.

**Why not bash:** scales poorly past ~500 LOC, JSON shaping is
painful, error envelopes become hand-rolled awk.

**Why not Go/Rust:** overkill for a hobbyist tool; slower iteration.

### 6.2 Project layout

```
~/projects/irisctl/
├── pyproject.toml          # uv-managed
├── Makefile                # .venv/bin/ prefixes (per CLAUDE.md hard rule)
├── README.md
├── src/irisctl/
│   ├── __init__.py
│   ├── cli.py              # argparse tree + dispatch
│   ├── config.py           # profiles, env, defaults
│   ├── output.py           # JSON envelope, human renderer
│   ├── http_api.py         # thin wrappers for /api/monitor/* and /api/atelier/*
│   ├── docker_api.py       # docker inspect / start / stop / cp wrappers
│   ├── exec_session.py     # iris session heredoc with HALT injection
│   ├── license.py          # LU pre-check helper
│   └── commands/
│       ├── status.py
│       ├── license.py
│       ├── metrics.py
│       ├── source.py
│       ├── exec_cmd.py
│       ├── sql.py
│       ├── lifecycle.py
│       └── persistence.py
└── tests/
    ├── conftest.py         # spins up a clean foia container per session
    ├── test_status.py
    ├── test_license.py
    ├── test_exec.py
    └── …
```

### 6.3 Dependencies

| Tool | Why |
|---|---|
| Python 3.11+ | tomllib, `match`, modern typing |
| `httpx` | sync + retries + connect timeouts |
| `click` (or argparse) | CLI tree |
| `rich` (optional) | only if `--human` mode needs tables |
| `docker` Python SDK | optional; can also shell out to `docker` CLI |
| `pytest` | testing |
| `ruff`, `mypy` | per CLAUDE.md |

Runtime: `docker` CLI available on PATH; container running before
ops that need it (start handles its own bootstrap).

### 6.4 License pre-check pattern

Implemented once, used by every LU-consuming command:

```python
def precheck_license(profile, op_cost: int = 1):
    m = http_api.metrics(profile, prefix="iris_license_")
    consumed = int(m["iris_license_consumed"])
    available = int(m["iris_license_available"])
    cap = consumed + available
    if available - op_cost < profile.license_reserve:
        raise IrisCtlError(
            code="license_exhausted",
            message=f"Need {op_cost} LU; only {available} free, "
                    f"reserve={profile.license_reserve}, cap={cap}",
            hint="irisctl license users",
        )
```

### 6.5 Atelier version probing

Done lazily on first `source` subcommand and cached in
`~/.cache/irisctl/<profile>.json`:

```python
for v in ("v6", "v5", "v4", "v3", "v2", "v1"):
    r = httpx.get(f"{base}/api/atelier/{v}/", auth=auth, timeout=2)
    if r.status_code in (200, 401):  # 401 means present, just unauth'd
        cache.atelier_version = v
        break
```

### 6.6 docker-exec heredoc safety

The `exec_session` module is the one place that touches
`docker exec` — every other module routes through HTTP. Two
guarantees:

1. **Always append `HALT`.** If user-supplied script ends with
   `QUIT`/`Q`, replace with `HALT`.
2. **Always use `<<'IRISCTL_EOF'`** (single-quoted heredoc tag) so
   `$VARS` in the user's script aren't shell-expanded.

```python
def session_exec(profile, ns: str, script: str) -> str:
    if not _ends_with_halt(script):
        script += "\nHALT\n"
    return subprocess.check_output(
        ["docker", "exec", "-i", profile.container,
         "iris", "session", "IRIS", "-U", ns],
        input=script,
        text=True,
        timeout=profile.exec_timeout,
    )
```

---

## 7. Phasing

Each phase is independently shippable; AI users get value from Phase 1
alone.

### Phase 1 — Read-only floor (no LUs, no auth)

**Subcommands:** `status`, `version`, `ports`, `logs`, `alerts`,
`health`, `license`, `license watch`, `metrics`, `metrics describe`,
`metrics scrape`.

**LOC estimate:** ~400.

**Tests:** integration tests against the running `foia` container.

**Ship criterion:** AI agent can answer "is the system OK", "what's
the license use", "what's in messages.log" with one command each.

### Phase 2 — Execute (LU-consuming)

**Subcommands:** `exec`, `sql`, `shell`. License pre-check
infrastructure.

**LOC estimate:** +200.

**Tests:** including license-exhaustion path (set
`license_reserve=8` and confirm exec is refused).

**Ship criterion:** AI agent can run ObjectScript and SQL without
typing heredocs or remembering `HALT`.

### Phase 3 — Source CRUD

**Subcommands:** `source list/get/put/delete/compile/search/diff`,
`namespaces`. Atelier version auto-probe. Auth handling.

**LOC estimate:** +250.

**Tests:** round-trip a routine; compile error path; auth-required
path.

**Ship criterion:** AI agent can read, modify, and compile routines
without learning the Atelier protocol.

### Phase 4 — Lifecycle & persistence

**Subcommands:** `start`, `stop`, `restart`, `recreate`, `backup`,
`restore`, `config show`, `config merge`.

**LOC estimate:** +200.

**Tests:** backup → restore round-trip; verify zero-loss against
[INSTALL_GUIDE.md §7](INSTALL_GUIDE.md).

**Ship criterion:** Whole disaster-recovery cycle scriptable.

### Phase 5 — Polish

Profiles, shell completion, `--watch` modes, `which` debug command,
JSON-RPC mode (for AI agents that want a single persistent process to
talk to instead of spawning many CLI calls), pip-installable
distribution.

**LOC estimate:** +250.

---

## 8. Testing strategy

1. **Pytest harness with session-scoped fixture** that ensures a clean
   `foia` container is up; `irisctl status` is the readiness probe.
2. **Real container only.** No mocking IRIS responses. Per
   `~/.claude/CLAUDE.md` "No mocks unless unavoidable — prefer real
   objects and fakes."
3. **License-budgeted tests.** A per-session counter caps total
   LU-consuming test calls at `cap - 2`; tests that would exceed are
   skipped with a clear reason.
4. **Snapshot tests for JSON envelopes.** `pytest-snapshot` for the
   shape, with hand-curated examples.
5. **Integration tests double as documentation.** Each test is a
   "here's how to use this subcommand" example.

---

## 9. Risks & open questions

1. **Auth: how to store creds.**
   - Option A: env var per profile (simplest; matches CLAUDE.md
     "no secrets in files" implicit rule).
   - Option B: OS keyring via the `keyring` package (nicer UX, pulls
     in a dependency).
   - Option C: prompt every time (too painful for AI use).
   - **Proposal: A by default, B opt-in.**

2. **Atelier in unauth mode?** The `/api/monitor/*` web app is
   unauthenticated in this image; possibly `/api/atelier/*` could be
   too if we configure it that way. Worth investigating to remove the
   auth burden from source CRUD entirely. Trade-off: portal allows
   anyone on localhost to compile arbitrary code.

3. **Compatibility matrix.** Pin against IRIS 2026.1 first; document
   what's needed to support 2024.x / 2025.x. Atelier endpoint
   versioning makes this easy; the `iris` CLI is stable.

4. **Multi-instance future.** The profile system handles this from
   day 1, but only one profile will be exercised initially. Don't
   over-engineer.

5. **Naming.** `irisctl` reads naturally and matches `kubectl`/
   `systemctl`. Alternatives considered: `irisx` (too cute),
   `iris-cli` (collides with the existing in-container `iris`
   command), `foiactl` (project-specific; less reusable for other
   instances). **Pick: `irisctl`.**

6. **Distribution.** `~/scripts/bin/irisctl` symlink to the project
   entrypoint for personal use; eventually `pipx install irisctl`
   from a private index for portability.

7. **Should `iris stats -L` be wrapped?** Probably not — the
   `/api/monitor/metrics` route gives the same answer without
   consuming an LU. Skip the `irisstat` surface entirely except
   maybe a single `irisctl stat <flag>` escape hatch.

8. **Long-running shell.** `irisctl shell` is a thin pass-through
   that holds an LU as long as the user's terminal is open — it
   exists for parity but isn't really a wrapper feature. Consider
   omitting from Phase 1.

---

## 10. What this displaces

When this lands, the following can retire:

| Replaced | Replacement |
|---|---|
| `~/scripts/bin/foia-license` | `irisctl license` |
| Hand-typed `docker exec -i foia iris session IRIS …` | `irisctl exec` |
| `docker run --rm --user 0 -v ~/data/foia-iris:/data:ro alpine tail …` | `irisctl logs` |
| `docker run --rm --network host alpine sh -c 'wget -qO- …'` | `irisctl metrics` / `irisctl alerts` |
| Restore recipes in [INSTALL_GUIDE.md §8](INSTALL_GUIDE.md) | `irisctl recreate` / `irisctl restore` |

The INSTALL_GUIDE keeps the manual recipes — they remain the
ground-truth fallback if the wrapper itself is broken.

---

## 11. Out of scope

- A long-running daemon. Stateless commands compose better.
- A web UI. The Mgmt Portal already exists at `/csp/sys/`.
- Wrapping every IRIS API. Only the surfaces an AI agent or operator
  reaches for in normal work — the `irisctl which` escape hatch
  documents the underlying command for the rest.
- Cross-platform (Windows). Linux-only is fine; the surface doc
  notes Windows differences for context but the wrapper targets
  the host OS the FOIA container runs on.
- Replacing the in-container `iris` CLI. That tool is stable and
  authoritative; the wrapper sits above it.

---

## 12. Bootstrapping next steps

If this proposal is accepted:

1. Create `~/projects/irisctl/` from `~/claude/templates/python/`.
2. Implement Phase 1 (~400 LOC, ~1 session).
3. Symlink `~/scripts/bin/irisctl` → project entrypoint.
4. Replace `~/scripts/bin/foia-license` body with
   `exec irisctl license "$@"` (keeping the script for muscle-memory).
5. Iterate Phases 2–5 as needed; each ships independently.

The whole tool is small enough that a complete first version
(Phases 1–3) is realistic in a single afternoon's work.
