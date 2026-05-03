# irisctl User's Guide

A programmer- and AI-friendly CLI wrapper for InterSystems IRIS
Community Edition Docker containers. One consistent JSON-first
surface that hides the patchwork of `docker exec`, heredocs,
`iris session`, host-network helpers, license bookkeeping, HTTP
probes, and CSP page paths that you'd otherwise re-type for every
task.

This guide is the canonical reference: what the tool does, how it's
designed, how to install and configure it, every command, common
workflows, and the lessons we learned wiring it up against a live
container.

> **Companion documents.** This guide draws on three deeper references
> already in this repo, all worth reading on their own:
>
> - [docs/iris-cli-surface.md](iris-cli-surface.md) — what's actually
>   underneath the wrapper: every IRIS subcommand, every HTTP
>   endpoint, every env var, every gotcha.
> - [docs/iris-cli-plan.md](iris-cli-plan.md) — the original 5-phase
>   proposal and design contract. Read this if you want the *why*
>   for a particular decision.
> - [docs/mctl-composite.md](mctl-composite.md) — irisctl ↔ ydbctl
>   side-by-side, classifying every operation as MUMPS-portable,
>   IRIS-only, or YottaDB-only.

---

## Contents

1. [What irisctl is, and what it isn't](#1-what-irisctl-is-and-what-it-isnt)
2. [Background](#2-background)
   - [Design philosophy](#21-design-philosophy)
   - [The CLI surface being wrapped](#22-the-cli-surface-being-wrapped)
   - [Implementation plan: 5 phases](#23-implementation-plan-5-phases)
3. [Installation and setup](#3-installation-and-setup)
4. [Configuration](#4-configuration)
5. [Quick start](#5-quick-start)
6. [Command reference](#6-command-reference)
   - [Phase 1: read-only inspection](#62-phase-1--read-only-inspection)
   - [Phase 2: execution](#63-phase-2--m--objectscript-execution)
   - [Phase 3: source CRUD via Atelier](#64-phase-3--source-crud-via-atelier)
   - [Phase 4: lifecycle + persistence](#65-phase-4--lifecycle--persistence)
   - [Phase 5: convenience + JSON-RPC](#66-phase-5--convenience--json-rpc)
7. [Output contract](#7-output-contract)
8. [Common workflows](#8-common-workflows)
9. [Troubleshooting](#9-troubleshooting)
10. [Architectural lessons](#10-architectural-lessons-captured-during-the-build)
11. [Sibling project: ydbctl](#11-sibling-project-ydbctl)
12. [What's next](#12-whats-next)
13. [Further reading](#13-further-reading)

---

## 1. What irisctl is, and what it isn't

**It is** a single command — `irisctl` — that drives a Dockerized
IRIS Community Edition instance through ~30 subcommands grouped into
five phases. Every command emits a versioned JSON envelope by default
(or a human-readable table with `--human`). Every command is tested
end-to-end against a real IRIS container.

```bash
$ irisctl license --human
consumed        1
available       7
cap             8
percent_used    13
days_remaining  327

$ irisctl status --human
container    {'status': 'running', 'running': True, 'health': 'healthy', ...}
listeners    [{'role': 'superserver', 'host_port': 1972, 'reachable': True}, ...]
license      {'consumed': 1, 'available': 7, 'cap': 8, 'percent_used': 13, ...}
system_state {'state': 0.0, 'alerts': 0.0, 'alerts_new': 0.0}

$ irisctl exec --ns %SYS 'W $ZV,!'
{"v":1,"ok":true,"command":"exec","data":{"namespace":"%SYS",
 "output":"\nIRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.1 ..."}}
```

**It isn't** a replacement for the in-container `iris` command-line
tool, the Management Portal, or the Atelier protocol. Those remain
canonical and authoritative; irisctl just makes them easier to drive
from a script or an AI agent. The `irisctl which <op>` subcommand
prints the underlying invocation for any operation, exactly so you
can drop down to the raw tool when you need to.

**It also isn't** an ObjectScript language tool. M / ObjectScript
language tooling lives elsewhere; irisctl is for *managing the
container* and the database it holds, not the M code itself.

---

## 2. Background

### 2.1 Design philosophy

The five principles, in order of importance:

1. **JSON-first.** Default output is a versioned envelope
   (`{"v": 1, "ok": true, "command": ..., "data": ..., "warnings": []}`).
   `--human` swaps to a table for terminal use; `--pretty` indents
   the JSON. The shape never changes between commands. AI agents
   can rely on it.

2. **Real-container testing only.** Per
   [the project plan §8](iris-cli-plan.md) and the global
   `~/.claude/CLAUDE.md` "no mocks unless unavoidable" rule, every
   integration test runs against an actual `foia` IRIS Community
   container. There is no mocked IRIS anywhere in the codebase.
   The cost is some test slowness (~12s for 233 tests); the payoff
   is that bugs surface against the real binaries, not against
   hypothetical stubs.

3. **HTTP-first, exec-last.** Every read-only operation goes through
   `/api/monitor/*` first (free, no LU consumed). Falls back to
   `docker inspect` or host-helper-container reads. Only LU-consuming
   commands (`exec`, `sql`, `shell`) actually `docker exec` into the
   container. This minimizes the cost of routine inspection.

4. **License-aware.** Every LU-consuming subcommand pre-checks
   `iris_license_consumed` from `/api/monitor/metrics` and refuses
   when the budget is too tight (default: refuse if fewer than
   `1 + reserve` LUs free). Bypass with `--force`. Each call also
   auto-retries once on transient `<LICENSE LIMIT EXCEEDED>` after
   a 1-second wait — the metrics endpoint can lag actual session
   state by a few hundred milliseconds.

5. **Symmetric with `ydbctl`.** The sibling tool for YottaDB Docker
   containers uses the *same* envelope shape, *same* error codes
   where they map, and identical subcommand names where the concept
   does (`status`, `version`, `ports`, `logs`, `exec`, `sql`,
   `shell`, `backup`, `restore`, `which`, `rpc`). An AI agent that
   learns one tool gets most of the other for free. See
   [docs/mctl-composite.md](mctl-composite.md) for the
   88-operation side-by-side comparison.

### 2.2 The CLI surface being wrapped

IRIS Community Edition runs as a **daemon**: one `iris-main`
wrapper as PID 1 (started under `tini`), hosting the IRIS
processes that own the database and the listener ports. This is
the opposite of YottaDB's "library, not daemon" model — and it
shapes everything:

- The Web Gateway on port 52773 hosts a rich HTTP surface:
  `/api/monitor/metrics` (Prometheus-format counters, 107 of them
  in 2026.1), `/api/monitor/alerts` (JSON), `/api/atelier/v6/`
  (source-code CRUD), `/csp/sys/` (Management Portal). irisctl
  uses these directly whenever possible.
- The Superserver on port 1972 multiplexes ODBC, JDBC, the IRIS
  Native SDK, the Atelier wire protocol, and `%Net.Remote.*`
  object-gateway connections.
- Community Edition ships with an 8-LU (license unit) cap.
  Steady-state idle is ~1 LU; every `iris session` adds 1 LU.
  irisctl tracks this via `/api/monitor/metrics`.
- After any unclean shutdown, IRIS auto-recovers on next start —
  no manual cleanup needed (unlike YottaDB's `mupip rundown`).

The full underlying surface — every binary, every flag, every
gotcha — lives in [docs/iris-cli-surface.md](iris-cli-surface.md).
High points:

| Layer | Purpose |
|---|---|
| `iris-main` (PID 2) | Wrapper that runs `iris start IRIS`, traps signals, handles `--before` / `--after` hooks, applies `ISC_CPF_MERGE_FILE` |
| `iris session IRIS -U <ns>` | The canonical M / ObjectScript shell — heredoc-friendly |
| `iris merge IRIS <file>` | Only safe way to mutate `iris.cpf` while running |
| `/api/monitor/metrics` | 107 Prometheus counters; unauthenticated by default on this image |
| `/api/atelier/v6/` | Source-code REST API used by VS Code IRIS extension; auth-gated |
| `/csp/sys/...` | Management Portal CSP pages |
| `iris.cpf` | Live config — namespaces, mappings, security, journaling |

irisctl wraps all of these. The `iris terminal` interactive shell
isn't directly wrapped — `irisctl shell` does an `os.execvp` into
`docker exec -it ... iris session IRIS` so your terminal connects
to the IRIS prompt with no shimming.

### 2.3 Implementation plan: 5 phases

The build follows the phasing locked in
[docs/iris-cli-plan.md](iris-cli-plan.md):

| Phase | Theme | Subcommands |
|---|---|---|
| 1 | Read-only floor (no LU, no auth) | `status`, `version`, `ports`, `logs`, `alerts`, `health`, `license` (incl. `watch` / `users`), `metrics` (incl. `describe` / `scrape`) |
| 2 | LU-consuming execution | `exec`, `sql`, `shell` |
| 3 | Source CRUD via Atelier (auth-gated) | `namespaces`, `source list/get/put/delete/compile` |
| 4 | Lifecycle + persistence | `start`, `stop`, `restart`, `recreate`, `backup`, `restore`, `config show`, `config merge` |
| 5 | Convenience + AI integration | `which`, `portal`, `docs`, `--watch` mode, JSON-RPC server (`rpc`), shell completion |

Each phase shipped in its own commit, independently testable. The
commit log is the canonical timeline; pipx packaging was
deliberately skipped per Rafael's 2026-05-03 brief.

---

## 3. Installation and setup

Three things have to be in place: a Docker daemon, an IRIS
Community Edition container, and the `irisctl` Python project.

### 3.1 Prerequisites

| Item | Why |
|---|---|
| Docker | Every command shells into a container via `docker exec` or HTTP |
| Python ≥ 3.12 | uv-managed venv; modern typing |
| `uv` | Project package manager (per `~/.claude/CLAUDE.md`) |
| ~10 GB free disk | IRIS image (~3 GB) + `IRIS.DAT` (~4.6 GB) + occasional backups |

### 3.2 Bring up an IRIS container

The default profile expects a container named `foia` running FOIA
VistA on IRIS Community Edition, with `~/data/foia-iris/`
bind-mounted to `/usr/irissys/mgr` + `iris.cpf`. The full recipe is
documented in
[docker-vista-fork's INSTALL_GUIDE.md](https://github.com/rafael5/docker-vista-fork/blob/main/INSTALL_GUIDE.md);
the short form:

```bash
# After cloning docker-vista-fork and downloading the FOIA distribution:
docker build -t foia IRIS/docker-iris/
docker run --name foia -d \
    -v ~/data/foia-iris/mgr:/usr/irissys/mgr \
    -v ~/data/foia-iris/iris.cpf:/usr/irissys/iris.cpf \
    -p 1972:1972 -p 52773:52773 -p 9430:9430 -p 8001:8001 \
    foia
```

The bind-mount layout is what makes `docker rm foia` zero-loss: all
persistent state (the VistA DAT, the security DB, journals, the
CPF) lives on the host volume. Restoring after teardown is a single
`docker run` away.

After ~25s the four listeners come up:
- 1972 — IRIS superserver (ODBC/JDBC/Native SDK)
- 52773 — Management Portal + REST APIs
- 9430 — VistA RPC Broker (CPRS)
- 8001 — VistALink

> **Why the `foia` container is the test target.** This is Rafael's
> active FOIA VistA install on IRIS Community. It's volume-backed,
> permission-restricted (UID 51773 / mode 700), and has been
> through a real first-login password change. Test fixtures rely
> on those properties. If you point irisctl at a different IRIS
> instance, override `IRISCTL_CONTAINER` and adjust the auth env
> vars accordingly.

### 3.3 Set up the project

```bash
git clone https://github.com/rafael5/irisctl.git
cd irisctl
make install         # uv sync + pre-commit hooks
make test            # 233 tests, ~12s — confirms container is reachable
```

To use the `irisctl` command directly anywhere, symlink the venv
entrypoint onto your `PATH`:

```bash
ln -s ~/projects/irisctl/.venv/bin/irisctl ~/scripts/bin/irisctl
```

(Or invoke as `python -m irisctl ...` — both work.)

### 3.4 Optional: shell completion

argcomplete is wired into the CLI parser. Activate by adding to
your shell rc:

```bash
# bash / zsh
eval "$(register-python-argcomplete irisctl)"
```

After that, `irisctl <Tab>` completes subcommands and flags.

---

## 4. Configuration

### 4.1 Resolution order

Profile values resolve in this order (lowest to highest precedence):

1. Built-in defaults (`foia` container, `~/data/foia-iris`,
   `127.0.0.1:52773` etc.).
2. `~/.config/irisctl/config.toml`, the `[profiles.<name>]` table
   for the active profile.
3. `IRISCTL_*` environment variables.
4. CLI flags (only `--profile NAME` selects which profile is active).

### 4.2 The TOML config file

```toml
default_profile = "foia"

[profiles.foia]
container         = "foia"
host              = "127.0.0.1"
web_port          = 52773
superserver_port  = 1972
rpc_port          = 9430
vistalink_port    = 8001
data_dir          = "~/data/foia-iris"
license_reserve   = 1                   # refuse LU ops below this many free
auth_user         = "_SYSTEM"
auth_pw_env       = "IRISCTL_FOIA_PW"   # name of env var holding pw

[profiles.foia.atelier]
version = "auto"   # "auto" probes v6→v5→…→v1 once and caches

# A second profile for a fresh upstream IRIS Community image:
[profiles.upstream]
container         = "iris-community"
host              = "127.0.0.1"
web_port          = 52773
data_dir          = "~/data/iris-community"
```

Switch with `irisctl --profile upstream status` or
`IRISCTL_PROFILE=upstream irisctl status`.

### 4.3 Environment variables

| Variable | Effect |
|---|---|
| `IRISCTL_PROFILE` | Select a profile |
| `IRISCTL_CONTAINER` | Override container name |
| `IRISCTL_HOST` | Override host (default `127.0.0.1`) |
| `IRISCTL_WEB_PORT` | Override Web Gateway port (default `52773`) |
| `IRISCTL_SUPERSERVER_PORT` | Override Superserver port (default `1972`) |
| `IRISCTL_DATA_DIR` | Override the host data directory |
| `IRISCTL_AUTH_USER` | Atelier user |
| `IRISCTL_AUTH_PW` | Atelier password (direct) |
| `IRISCTL_AUTH_PW_ENV` | Name of a *third* env var holding the password (indirection — keeps secrets out of shell history) |

### 4.4 Auth resolution

[Phase 3](#64-phase-3--source-crud-via-atelier) commands hit
auth-gated `/api/atelier/v6/*` endpoints. Credentials resolve in
this order:

1. `IRISCTL_AUTH_USER` + `IRISCTL_AUTH_PW` (direct).
2. `auth_user` from TOML + `IRISCTL_AUTH_PW`.
3. `auth_user` from TOML + env var named by `auth_pw_env`.

When none resolve, every Phase 3 subcommand returns `auth_required`
(exit code 5). When creds resolve but IRIS rejects them, the error
is `auth_failed` (also exit code 5).

> **Default IRIS credentials.** Fresh IRIS Community installs ship
> with `_SYSTEM` / `SYS` and force a password change on first
> portal login. The `foia` container in this repo has been through
> that change, so the defaults will not work — you must supply the
> actual password through `IRISCTL_AUTH_PW`.

---

## 5. Quick start

The five commands you'll run most:

```bash
# License snapshot (replaces ~/scripts/bin/foia-license):
irisctl license --human

# Composite health check:
irisctl health --human

# What namespaces exist? (Atelier — needs creds)
irisctl namespaces --human

# Run a one-line ObjectScript expression in %SYS:
irisctl exec --ns %SYS 'W $ZV,!'

# Tail the IRIS messages.log:
irisctl logs --tail 50
```

If `health` shows `verdict: green` and listeners are all reachable,
you're set.

---

## 6. Command reference

This section is comprehensive — every subcommand, every flag,
every error path. Skip ahead to whichever phase you need.

### 6.1 Global flags

These work *before or after* the subcommand:

| Flag | Effect |
|---|---|
| `--profile NAME` | Select a profile (default from `default_profile`) |
| `--json` | JSON output (default) |
| `--human` | Render envelope as a human-readable table |
| `--pretty` | Indent JSON output |

### 6.2 Phase 1 — read-only inspection

No mutation, no LU consumed, no auth required. Safe to run as
often as you like. All but two commands (`logs`, `version`) hit
the HTTP `/api/monitor/*` endpoints directly — the ones that
matter for license + system state are essentially free.

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl status` | Composite container + listeners + license + system_state | `docker inspect` + TCP probe + `/api/monitor/metrics` |
| `irisctl version` | IRIS engine + image labels | `docker inspect` |
| `irisctl ports` | Per-listener reachability table | `docker inspect` + TCP probe |
| `irisctl logs [--tail N]` | Tail `messages.log` | host-helper alpine `tail` |
| `irisctl alerts` | All `alerts.log` entries since last scrape | `/api/monitor/alerts` |
| `irisctl health` | Green/yellow verdict with check breakdown | composite |
| `irisctl license` | Current LU consumption snapshot | `/api/monitor/metrics` |
| `irisctl license --watch [--interval N]` | Poll the license counters | shared `watch_loop` |
| `irisctl metrics [--prefix P]` | Filtered Prometheus counters | `/api/monitor/metrics` |
| `irisctl metrics describe NAME` | Single-counter detail | `/api/monitor/metrics` |
| `irisctl metrics scrape` | Raw Prometheus text | `/api/monitor/metrics` |
| `irisctl which [OP]` | Explain underlying mechanism for any op | static registry |

Examples:

```bash
# What does irisctl exec actually do?
$ irisctl which exec --human
op          exec
mechanism   docker exec -i + iris session heredoc (HALT-injected)
underlying  docker exec -i foia iris session IRIS -U <ns> <<'EOF' <script>\nHALT\nEOF
lu_cost     1

# Filter to a metric family:
$ irisctl metrics --prefix iris_db_ --human

# What's the canonical license metric?
$ irisctl metrics describe iris_license_percent_used --human
name    iris_license_percent_used
help    Licenses in use (percentage)
type    gauge
labels  {}
value   13.0

# Live license-monitoring loop (Ctrl-C to exit):
$ irisctl license --watch --interval 5 --human
```

### 6.3 Phase 2 — M / ObjectScript execution

Each call consumes 1 LU. The wrapper pre-checks
`/api/monitor/metrics` and refuses if the budget is too tight (less
than `1 + reserve` LUs free). Override with `--force`.

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl exec --ns NS '<code>'` | Run ObjectScript via heredoc | `iris session IRIS -U NS` + HALT injection |
| `irisctl exec --ns NS --stdin` | Read script from stdin | same |
| `irisctl exec --ns NS --file PATH` | Read script from a host file | same |
| `irisctl sql --ns NS '<sql>'` | Run SQL, return rows as JSON | wraps `%SQL.Statement.%ExecDirect` |
| `irisctl sql --ns NS --file PATH` | DDL import | same |
| `irisctl shell [--ns NS]` | Interactive IRIS terminal | `os.execvp` into `docker exec -it ... iris session` |

Phase 2 commands share three guarantees:

1. **License pre-check** — refuses near the cap unless `--force` is
   given. Output: `license_exhausted` error envelope, exit code 4.
2. **HALT injection** — every script gets a trailing `HALT` if
   missing, and trailing `QUIT`/`Q` is replaced with `HALT`. Avoids
   the classic "QUIT only exits the current frame" hang.
3. **License-retry on `<LICENSE LIMIT EXCEEDED>`** — one automatic
   retry after a 1-second pause, in case the metrics endpoint
   hadn't caught up to live LU state.

Examples:

```bash
# Print the IRIS version banner from %SYS:
irisctl exec --ns %SYS 'W $ZV,!'

# Run a multi-line script via heredoc (preserves the heredoc HALT trick):
irisctl exec --ns USER --stdin <<'END'
S total=0
F i=1:1:10 S total=total+i
W "Sum: ",total,!
END

# SQL with structured rows back:
irisctl sql --ns USER 'SELECT 1+1 AS two' --human
namespace  USER
columns    ['two']
rows       [{'two': '2'}]
rowcount   1

# Drop into the interactive IRIS terminal (consumes 1 LU for whole session):
irisctl shell --ns USER
```

### 6.4 Phase 3 — source CRUD via Atelier

Auth-gated source-code CRUD over `/api/atelier/v6/*` (the same API
the VS Code ObjectScript extension uses). The Atelier version is
auto-probed (v6 → v1) once per session and cached. Each call
consumes 1 LU on the IRIS side.

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl namespaces` | List namespaces + Atelier version | `GET /api/atelier/v6/` |
| `irisctl source list <NS> [pattern]` | List documents (`.mac`, `.cls`, etc.) | `GET /api/atelier/v6/<ns>/docnames` |
| `irisctl source get <NS> <doc>` | Read source content | `GET /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source put <NS> <doc> [--file F\|--stdin]` | Upsert a document | `PUT /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source delete <NS> <doc>` | Delete a document | `DELETE /api/atelier/v6/<ns>/doc/<doc>` |
| `irisctl source compile <NS> <doc...> [--flags ck]` | Compile listed documents | `POST /api/atelier/v6/<ns>/action/compile` |

Examples:

```bash
$ export IRISCTL_AUTH_USER=_SYSTEM
$ export IRISCTL_AUTH_PW='your-real-password-here'

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

# Round-trip a routine:
$ echo 'myroutine ; demo' '\n' ' W "hello",!' '\n' ' Q' \
    | irisctl source put USER myroutine.mac --stdin

$ irisctl source get USER myroutine.mac
{"v":1,"ok":true,"command":"source","data":{"namespace":"USER",
 "name":"myroutine.mac","content":["myroutine ; demo"," W \"hello\",!"," Q"],
 "lines":3,"ts":"..."}}

$ irisctl source compile USER myroutine.mac
{"v":1,"ok":true,"command":"source","data":{"namespace":"USER",
 "compiled":1,"flags":"ck",...}}

$ irisctl source delete USER myroutine.mac
```

> **Two-tier auth errors.** When no creds resolve at all,
> Phase 3 commands return `auth_required` (exit 5). When creds
> resolve but IRIS rejects them, the error is `auth_failed` (also
> exit 5). Both are exit code 5 but distinguishable for tooling.

### 6.5 Phase 4 — lifecycle + persistence

Container-level state changes. `recreate` and `restore` are
`--yes`-gated; both support `--dry-run` to print the planned argv
without doing anything.

| Command | Purpose | Mechanism |
|---|---|---|
| `irisctl start [--wait-timeout N]` | Start the container; wait for listeners | `docker start` + TCP probe |
| `irisctl stop [--timeout N]` | Graceful shutdown (default 60s — 10s isn't enough for a busy instance) | `docker stop -t N` |
| `irisctl restart` | stop + start | composite |
| `irisctl recreate --image I --yes` | Remove + run from host volume | `docker rm` + `docker run` per [INSTALL_GUIDE §8](https://github.com/rafael5/docker-vista-fork/blob/main/INSTALL_GUIDE.md) |
| `irisctl backup [--to PATH] [--offline]` | Tar host volume to a backup tarball | helper `alpine tar` |
| `irisctl restore --from F --yes` | Replace host volume from tarball (destructive) | helper `alpine` wipe + untar |
| `irisctl config show` | Read live `iris.cpf` | helper `alpine cat` |
| `irisctl config merge FILE [--dry-run]` | Apply CPF fragment via `iris merge` | `docker cp` + `docker exec iris merge` |

Safety guardrails:

- **`recreate` and `restore` require `--yes`** — they wipe Docker
  state. Both also accept `--dry-run` to print the planned
  argv/steps.
- **`backup` defaults to `--online`** (live tar, faster); pass
  `--offline` for stop+tar+start consistency.
- **`config merge` is the only safe CPF mutation path.** Direct
  edits to a running `iris.cpf` get overwritten on shutdown.
- Full container cycles (real stop+start, real backup) are gated
  behind `@pytest.mark.slow` so default `make test` stays under
  12s. Run them explicitly with `make test-slow` (~60-180s).

Examples:

```bash
# Snapshot the current state before risky work:
irisctl backup --to ~/data/backups/foia/$(date +%Y%m%d)

# Inspect the live CPF (14 KB):
irisctl config show | jq -r '.data.text' | grep '^\[' | head -20

# Apply a small CPF fragment (dry-run first):
echo '[Defaults]
NewKey=42' > /tmp/frag.cpf
irisctl config merge /tmp/frag.cpf --dry-run --pretty

# Recreate the container from the host volume, no data loss:
irisctl recreate --dry-run | jq '.data.argv'  # inspect first
irisctl recreate --yes
```

### 6.6 Phase 5 — convenience + JSON-RPC

Quality-of-life commands and the AI-friendly JSON-RPC server.

| Command | Purpose |
|---|---|
| `irisctl which [OP]` | Explain underlying mechanism for any op |
| `irisctl portal [PATH]` | Open Mgmt Portal in default browser |
| `irisctl docs KEY` | Open InterSystems docs page for KEY |
| `irisctl rpc` | JSON-RPC 2.0 server on stdin/stdout |
| `irisctl status --watch [--interval N]` | Poll status until interrupted |
| `irisctl license --watch [--interval N]` | Poll license until interrupted |
| Shell completion | argcomplete-driven bash/zsh/fish |

#### `irisctl rpc` — JSON-RPC 2.0 single-process mode

The marquee Phase 5 feature for AI use. Reads newline-delimited
JSON-RPC 2.0 requests on stdin, writes responses on stdout. One
persistent process drives ~30 registered methods without paying
argparse + config-load startup per call:

```bash
$ printf '%s\n%s\n' \
    '{"jsonrpc":"2.0","method":"license","id":1}' \
    '{"jsonrpc":"2.0","method":"which","params":{"op":"exec"},"id":2}' \
  | irisctl rpc
{"jsonrpc":"2.0","id":1,"result":{"v":1,"ok":true,"command":"license",
 "data":{"consumed":1,"available":7,"cap":8,"percent_used":13,"days_remaining":327}}}
{"jsonrpc":"2.0","id":2,"result":{"v":1,"ok":true,"command":"which",
 "data":{"op":"exec","mechanism":"docker exec -i + iris session ...","lu_cost":1}}}
```

All Phase 1–5 commands are exposed as RPC methods (~30 total) — see
the registry in [src/irisctl/rpc.py](../src/irisctl/rpc.py)
`METHODS`. Sub-verbed commands use underscores: `metrics_describe`,
`metrics_scrape`, `source_list`, `source_get`, `source_put`,
`source_delete`, `source_compile`, `config_show`, `config_merge`.

Standard JSON-RPC 2.0 error codes apply: `-32700` parse error,
`-32600` invalid request, `-32601` method not found, `-32602`
invalid params, `-32603` internal error. Notifications (no `id`)
get no response.

#### `--watch` mode

`status` and `license` accept `--watch` for a poll loop. Each
iteration prints a fresh envelope; Ctrl-C exits cleanly with the
last result. The shared `watch_loop` is in
[src/irisctl/watch.py](../src/irisctl/watch.py).

```bash
# Watch the license counter every 5 seconds, JSON form:
irisctl license --watch --interval 5

# Composite status, human-formatted, every 10s:
irisctl status --watch --interval 10 --human
```

---

## 7. Output contract

### 7.1 Envelope shape

Every command emits one of these:

```json
{"v": 1, "ok": true, "command": "license", "data": {...}, "warnings": []}
{"v": 1, "ok": false, "command": "exec",
 "error": {"code": "license_exhausted", "message": "...",
           "hint": "...", "ref": "..."}}
```

Fields:

- `v`: schema version (currently 1)
- `ok`: boolean
- `command`: which subcommand emitted this
- `data` (success): a dict, list, or scalar — varies per command
- `warnings` (success, optional): list of human-readable strings
- `error` (failure): code + message + optional hint + optional doc ref

### 7.2 Error codes ↔ exit codes

Stable mapping — scripts can rely on these:

| Code | Exit | Meaning |
|---|---|---|
| `ok` | 0 | Command succeeded |
| `internal` | 1 | Unexpected wrapper bug |
| `usage` | 2 | Bad arguments / missing flag |
| `instance_not_running` | 3 | Container missing or stopped |
| `license_exhausted` | 4 | LU budget at/below threshold (IRIS-specific) |
| `auth_required` / `auth_failed` | 5 | Missing or rejected credentials |
| `not_found` | 6 | Namespace / document / metric missing |
| `iris_error` | 7 | Underlying IRIS error |
| `docker_error` | 8 | `docker` command failed |
| `network_error` | 9 | Port unreachable / HTTP request failed |

Note: the YottaDB `ydbctl` tool uses code 4 for `ipc_orphans`
(YottaDB has no LU concept; the analogous "you should fix this
before mutating" warning is orphan IPC keys). When you see code 4
from irisctl, it always means the LU budget is too tight — close
stray sessions and retry, or pass `--force`.

### 7.3 Human mode

`--human` renders the envelope as a key:value block (for dict data)
or a borderless table (for list-of-dicts data). Errors render as:

```
ERROR (license_exhausted): need 1 LU; only 0 free (consumed=8, cap=8, reserve=1).
                           Pass --force to bypass.
hint: irisctl license   # see current consumption
see:  docs/iris-cli-surface.md#10-gotchas
```

ANSI color is intentionally omitted — output stays pipe-safe.

---

## 8. Common workflows

### 8.1 Daily-driver health check

```bash
irisctl health --human
```

If verdict is `green`, you're done. If `yellow`, the failed checks
list points at the issue (typically license headroom or a stuck
listener).

### 8.2 License-watching during a busy period

```bash
# Pin one terminal to a live counter:
irisctl license --watch --interval 5 --human

# Or in JSON form, piped to your alerting tool:
irisctl license --watch --interval 30 \
  | jq -c 'select(.data.percent_used > 75)'
```

The watch loop polls `/api/monitor/metrics` every N seconds — no
LU consumed.

### 8.3 Cold backup before risky work

```bash
backup_dir=~/data/backups/foia/$(date +%Y%m%dT%H%M%S)

irisctl backup --offline --to "$backup_dir" --human
echo "snapshot at $backup_dir"

# Run your risky operation here ...

# If anything went wrong:
irisctl restore --from "$backup_dir/foia-iris-*.tgz" --yes
```

`--offline` is `docker stop` → tar → `docker start`, slower but
journal-consistent. The default `--online` is faster (tar against
the live volume) but can capture an in-flight transaction.

### 8.4 Run an ObjectScript routine

```bash
# Push a routine via Atelier:
cat > /tmp/myroutine.mac <<'END'
myroutine ; demo
 W "Hello from the wrapper",!
 Q
END
irisctl source put USER myroutine.mac --file /tmp/myroutine.mac
irisctl source compile USER myroutine.mac

# Now invoke it:
irisctl exec --ns USER 'D ^myroutine'

# Cleanup:
irisctl source delete USER myroutine.mac
```

### 8.5 Recover from `<LICENSE LIMIT EXCEEDED>` flood

```bash
# 1. Confirm:
irisctl license --human

# 2. See who's holding LUs (calls /csp/sys/op/UtilSysLicenseUse.csp):
irisctl license users --human

# 3. Close stray iris session shells, JDBC clients, etc.

# 4. Re-check:
irisctl license --human
```

If you're stuck, the wrapper auto-retries once on transient
`<LICENSE LIMIT EXCEEDED>` after a 1-second pause — most
non-saturated cases resolve themselves.

### 8.6 AI-agent integration via JSON-RPC

```bash
# Start one persistent irisctl rpc process from your agent:
exec 3>&1
coproc IRISCTL { irisctl rpc; }

# Send requests over stdin, read responses from stdout:
echo '{"jsonrpc":"2.0","method":"status","id":1}' >&"${IRISCTL[1]}"
read -r resp <&"${IRISCTL[0]}"
echo "$resp" | jq '.result.data.container.running'
```

This avoids ~30 forks per agent turn — significant when the agent
makes many small status checks. All ~30 methods reachable through
one process.

### 8.7 Open Management Portal pages

```bash
# Mgmt Portal home:
irisctl portal

# Live License Use page:
irisctl portal op/UtilSysLicenseUse.csp

# A specific docs reference:
irisctl docs ADOCK   # Running InterSystems Products in Containers
irisctl docs GCM_rest  # Monitoring IRIS via REST
```

Both `portal` and `docs` shell out to `xdg-open` (Linux) or `open`
(macOS). Use `--dry-run` to print the URL instead of opening it.

---

## 9. Troubleshooting

### 9.1 `<LICENSE LIMIT EXCEEDED>` on `iris session`

```
{"v":1,"ok":false,"command":"exec","error":{
  "code":"iris_error","message":"iris session exit 133: <LICENSE LIMIT EXCEEDED>"}}
```

This means the IRIS LU cap (8 on Community Edition) is saturated.
Close stray `iris session` shells, JDBC connections, etc. The
wrapper auto-retries once after a 1-second pause for transient
spikes. To bypass the pre-check entirely, pass `--force`:

```bash
irisctl exec --force --ns %SYS 'W $H,!'
```

### 9.2 Atelier returns 401

```
{"v":1,"ok":false,"command":"namespaces","error":{
  "code":"auth_required","message":"atelier endpoint requires credentials"}}
```

Set the auth env vars:

```bash
export IRISCTL_AUTH_USER=_SYSTEM
export IRISCTL_AUTH_PW='your-real-password'
```

Or use the indirection variant if you don't want the password in
shell history:

```bash
export IRISCTL_AUTH_USER=_SYSTEM
export IRISCTL_AUTH_PW_ENV=MY_VAULT_PW
export MY_VAULT_PW='...'   # populated from your secret manager
```

If creds are set but get rejected, the error code becomes
`auth_failed` — check the actual values.

### 9.3 `(unhealthy)` in `docker ps`

The IRIS Community image's built-in healthcheck probes via
`iris session`, which gets `<LICENSE LIMIT EXCEEDED>` once the LU
budget is saturated. So `docker ps` flips to `(unhealthy)` even
though the four listener ports are externally reachable. The
listeners are the source of truth, not the Docker health flag —
`irisctl health` knows this and won't false-alarm.

### 9.4 `messages.log` not at the default path

If `irisctl logs` errors out, IRIS may have been configured with a
non-default `ConsoleFile` in `iris.cpf`. Check:

```bash
irisctl config show | jq -r '.data.text' | grep -i console
```

Update the profile's `data_dir` or override with `IRISCTL_DATA_DIR`
to point at the correct location.

### 9.5 `iris.cpf` mutation gone wrong

Direct edits to the live `iris.cpf` file get overwritten on shutdown.
Always use `irisctl config merge`:

```bash
echo '[Defaults]
MyKey=42' > /tmp/frag.cpf
irisctl config merge /tmp/frag.cpf --dry-run   # inspect first
irisctl config merge /tmp/frag.cpf
```

### 9.6 First-login password change

A fresh IRIS Community install ships with `_SYSTEM` / `SYS` and
forces a change at first portal login. If you haven't yet logged in:

```bash
irisctl portal   # opens the portal
# log in as _SYSTEM / SYS, change the password when prompted

# Then set IRISCTL_AUTH_PW to the new value
```

### 9.7 LU saturation during rapid scripted use

If a tight script loop hits `<LICENSE LIMIT EXCEEDED>` even though
you only have a few sessions running, the metrics endpoint may be
lagging actual session state by ~1 second. The wrapper handles
this with a one-shot retry. If you still hit it:

```bash
# Add a small sleep between calls, or use rpc mode (one process):
irisctl rpc <<EOF
{"jsonrpc":"2.0","method":"exec","params":{"namespace":"%SYS","script":"W 1,!"},"id":1}
{"jsonrpc":"2.0","method":"exec","params":{"namespace":"%SYS","script":"W 2,!"},"id":2}
EOF
```

`rpc` mode is ~30× cheaper than re-spawning a Python process for
each call.

---

## 10. Architectural lessons (captured during the build)

These came from real hours debugging against the live container.
Save someone else from re-discovering them:

### 10.1 IRIS is a daemon, YottaDB is a library

This shapes irisctl's "HTTP-first, exec-last" preference. Most
read-only ops route through `/api/monitor/*` (free, no LU) and
only fall back to `docker exec` when the daemon's HTTP surface
doesn't expose the data. Compare with ydbctl, which has no HTTP
surface and routes everything through subprocesses.

### 10.2 `/api/monitor/*` is unauthenticated on this image

The `foia` Community-Edition install has the `/api/monitor` web
app set to unauthenticated — every Phase 1 command (license,
metrics, alerts, status) works with no creds. This is a real
property of this specific install, not a contract; on a hardened
deployment you'd need credentials. The wrapper would then return
`auth_required` cleanly.

### 10.3 The 8-LU Community cap is real, but ~7 LU is steady-state-free

Measurement (2026-05-03): post-`^ZSTU` with all listeners up,
`iris_license_consumed` reads `1`. Each `iris session` adds 1 LU.
Earlier `License limit exceeded` log entries we'd seen reflected
concurrent install-time activity, not steady-state listener
overhead. (This corrected an earlier "~5 LU cap" assumption — see
the [INSTALL_GUIDE.md](https://github.com/rafael5/docker-vista-fork/blob/main/INSTALL_GUIDE.md)
§9 in the docker-vista-fork repo.)

### 10.4 The metrics endpoint lags actual session state

The `iris_license_*` counters can be ~1 second behind real LU
state. A tight script loop can pre-check OK then fail with
`<LICENSE LIMIT EXCEEDED>`. The wrapper handles this with a
one-shot retry on detection of that error string —
[src/irisctl/exec_session.py](../src/irisctl/exec_session.py).

### 10.5 `HALT` ≠ `QUIT` in scripted sessions

`QUIT` only exits the current stack frame; `HALT` exits the IRIS
process. A heredoc that ends with `QUIT` hangs the `docker exec`.
The wrapper auto-replaces trailing `QUIT`/`Q` with `HALT` and
appends `HALT` if missing.

### 10.6 Docker `(unhealthy)` is a false-negative

The image's `HEALTHCHECK` script probes via `iris session`, which
fails with `<LICENSE LIMIT EXCEEDED>` once the LU budget saturates.
So `docker ps` shows `(unhealthy)` even when all listeners are
reachable. Trust the listener probes, not the Docker flag.

### 10.7 `docker stop -t 10` is too short for a busy IRIS

The default `docker stop` timeout (10s) often isn't enough for
IRIS to flush dirty buffers. The wrapper's `irisctl stop` defaults
to `-t 60`; tune up further for production loads.

### 10.8 Atelier is versioned at the *path* level

Every Atelier endpoint is at `/api/atelier/v6/...` (or v5/v4/...).
The bare `/api/atelier/` returns 404 in some builds. The wrapper
auto-probes v6 → v1 once per session, accepting `200` *or* `401`
as proof-of-existence (so the probe doesn't need credentials).

### 10.9 Default credentials are flagged "expired" at first login

A fresh IRIS Community install ships with `_SYSTEM` / `SYS` and
forces a password change on first portal login. The `foia`
container has been through that change, so the defaults won't
work — callers must supply the actual password through
`IRISCTL_AUTH_PW` (or via the indirection env var).

### 10.10 SuperServer port history: 51773 → 1972

Pre-2020.3 IRIS images used 51773. Current images (`latest-em`,
`latest-cd`) use 1972. Old client connection strings still pointing
at 51773 silently time out. The default profile uses 1972; old
configs may need updating.

---

## 11. Sibling project: ydbctl

[ydbctl](https://github.com/rafael5/ydbctl) is the same idea for
YottaDB Docker containers. It uses:

- The same envelope shape and error-code namespace
- Identical subcommand names where the concept maps cleanly
- The same `--profile` / `--human` / `--pretty` / `--watch` flags
- The same `rpc` JSON-RPC mode (different method registry)

Where they differ:

| Concern | irisctl | ydbctl |
|---|---|---|
| License model | LU-capped (Community: 8 LU) | None (Apache 2.0) |
| Error code 4 | `license_exhausted` | `ipc_orphans` |
| HTTP API surface | `/api/monitor/*`, `/api/atelier/*` | None (subprocess only) |
| Container default user | UID 51773 (`irisowner`) | root (gtmsecshr setuid) |
| Source-code CRUD | `source list/get/put/delete/compile` (M + classes) | `globals export/show` (M data only) |
| Recovery | Implicit (daemon does it) | Explicit (`rundown` / `recover`) |
| ObjectScript classes | First-class (the `.cls` suffix in `source` ops) | Not applicable |
| SQL | First-class (built-in via 1972) | Plugin (Octo / ROcto) |

Read the full 88-operation cross-classification in
[docs/mctl-composite.md](mctl-composite.md). For VistA workloads
specifically, **58% of operations are MUMPS-portable across both
backends** — the rest are admin-layer concerns invisible to VistA
itself.

---

## 12. What's next

All five phases are shipped. Possible future directions, none
currently planned:

- **Pipx packaging.** Skipped per the Phase 5 brief; would let
  `pipx install irisctl` work for distribution. The
  `[project.scripts]` entry already exists, so this is small work.
- **Multi-instance support.** The profile system handles this from
  day 1, but only one profile is exercised so far. Production
  setups with multiple IRIS instances would benefit from worked
  examples.
- **Atelier search/diff.** Per the plan §3.4, `source search` and
  `source diff` are deferred. They're cheap to add when needed.
- **`irisctl stat <flag>` escape hatch.** The plan deliberately
  doesn't wrap every `irisstat` flag — the metrics endpoint
  duplicates most of it. A thin pass-through for the few unique
  ones could be useful.
- **Auth keyring integration.** Currently passwords come from env
  vars. An optional `keyring` package fallback would be nicer for
  interactive use.

---

## 13. Further reading

### In this repo

- [docs/iris-cli-surface.md](iris-cli-surface.md) — the IRIS
  surface this wraps. 531 lines, fully cited against
  docs.intersystems.com.
- [docs/iris-cli-plan.md](iris-cli-plan.md) — the original 5-phase
  proposal with design contracts.
- [docs/mctl-composite.md](mctl-composite.md) — irisctl ↔ ydbctl
  side-by-side, 88 operations classified.
- [src/irisctl/rpc.py](../src/irisctl/rpc.py) `METHODS` —
  canonical list of every JSON-RPC method.
- [src/irisctl/commands/](../src/irisctl/commands/) — one module
  per subcommand; read the source for behavior contracts.

### InterSystems official documentation

- [Manage InterSystems IRIS Instances: The iris Command](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_using_instance)
- [Running InterSystems Products in Containers (ADOCK)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ADOCK)
- [Monitoring IRIS via REST (GCM_rest)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GCM_rest)
- [Source Code File REST API Reference (GSCF_ref)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSCF_ref)
- [Managing Superservers (GSA_manage_superserver)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_manage_superserver)
- [Using the Management Portal](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_using_portal)

### Sibling tools

- [ydbctl](https://github.com/rafael5/ydbctl) — same wrapper
  pattern for YottaDB. Read its
  [USER_GUIDE.md](https://github.com/rafael5/ydbctl/blob/main/docs/USER_GUIDE.md)
  alongside this one if you work with both backends.
- [docker-vista-fork](https://github.com/rafael5/docker-vista-fork)
  — Rafael's fork of WorldVistA's docker-vista, where the FOIA
  install layout this guide assumes originates. Its
  [INSTALL_GUIDE.md](https://github.com/rafael5/docker-vista-fork/blob/main/INSTALL_GUIDE.md)
  is the canonical reference for the `foia` container setup.
