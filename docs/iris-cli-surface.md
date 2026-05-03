# IRIS Docker Container — CLI / API Surface Reference

A comprehensive map of every way to drive an InterSystems IRIS Community
Edition Docker container programmatically. Compiled from the official
docs at docs.intersystems.com (System Administration Guide, container
docs, REST references), the InterSystems Developer Community, and live
inspection of `iris-community:latest-em` build `2026.1.0.234.1com`.

The intended audience is humans and AI agents who need a single
authoritative reference of which tools, flags, ports, endpoints, and
files exist — and how they fit together — without re-discovering the
surface on every task.

> **Live source of truth.** Some `iris` subcommands are listed in the
> in-container `iris help` output but only thinly documented in the
> public reference. When in doubt, run `iris help` in the running
> container — it overrides anything below for help-only flags.

---

## Scope

| Item | Value |
|---|---|
| Image | `containers.intersystems.com/intersystems/iris-community:latest-em` |
| Build verified | `2026.1.0.234.1com` (built 2026-04-23, platform-version `2026.1.0.234.1com`) |
| Default instance name | `IRIS` (`ISC_PACKAGE_INSTANCENAME`) |
| Entrypoint | `["/tini", "--", "/iris-main"]` — `tini` PID 1, then `iris-main` wrapper |
| Container user | `irisowner` UID/GID `51773:51773` |
| Working dir | `/home/irisowner` |
| Install root | `/usr/irissys` (`ISC_PACKAGE_INSTALLDIR`) |
| Healthcheck | `/irisHealth.sh` every 60s (script shipped in the image) |
| Exposed ports | 1972, 2188, 52773, 53773, 54773 |

---

## 1. Container entrypoint — `iris-main` flags

`iris-main` is the wrapper that runs inside the container as PID-2 (PID 1
is `tini`, which forwards signals). It runs hooks, starts IRIS, blocks
on signals, and runs a graceful shutdown on `SIGTERM`/`SIGINT`. All
flags are passed via the Docker `CMD`.

| Flag | Purpose | Example |
|---|---|---|
| `--check-caps true\|false` | Verify Linux capabilities (`CAP_SETUID`, `CAP_SETGID`) before start. Defaults to `true`; restrictive Kubernetes `securityContext` may need `false`. | `--check-caps false` |
| `--key <path>` | Copy a license key file from the path into `<install>/mgr/iris.key` for auto-activation. | `--key /run/secrets/iris.key` |
| `--before <cmd>` | Shell command run **before** `iris start`. Synchronous; nonzero exit aborts startup. | `--before "/scripts/preflight.sh"` |
| `--after <cmd>` | Shell command run **after** IRIS finishes its internal startup. | `--after "/scripts/load-data.sh"` |
| `--log <path>` | Mirror IRIS log to a file in addition to stdout. | `--log /var/log/iris-main.log` |
| `--password-file <path>` | One-shot: read first line as the new password for `_SYSTEM`/`Admin`/`SuperUser`; file is consumed and deleted. | `--password-file /run/secrets/pw` |
| `--ISCAgent ...` | Configure the optional ISCAgent sidecar (HA mirroring). Specifics not in the public ADOCK page. | — |
| `--help` | Print usage. | — |

**Execution order:** `--check-caps` → `--before` → `--key` install →
`iris start IRIS` → `ISC_CPF_MERGE_FILE` applied if set → `--after` →
block on signals.

**Signal handling.** SIGTERM/SIGINT trigger `iris stop IRIS quietly`
then exit 0; this is what makes `docker stop` safe. Default
`docker stop -t 10` may be too short for a busy instance — use
`docker stop -t 60`+.

> **No `iris-startup-script.sh` convention exists.** The supported
> hook surface is `--before` / `--after` plus the
> `IRIS_USERNAME`/`IRIS_PASSWORD`/`IRIS_NAMESPACE` first-boot env vars.
> Custom Dockerfiles typically `iris session IRIS < /tmp/iris.script`
> at *build* time, or invoke their own script via `--after`.

---

## 2. Environment variables

| Variable | Default | Purpose | Gotchas |
|---|---|---|---|
| `ISC_DATA_DIRECTORY` | unset | Activates **durable %SYS**. On first start, IRIS clones `mgr/`, journals, WIJ, security DB to this path; subsequent starts reuse it as live data. | Must be backed by a `--volume` mount; otherwise startup fails. UID 51773 must own/write it. NFS unsupported. |
| `ISC_CPF_INI_FILE` | unset | Path to a complete `iris.cpf` to seed on first boot. Replaces shipped defaults. | First-boot only; ignored once durable %SYS exists. |
| `ISC_CPF_MERGE_FILE` | unset | Path to a partial CPF merged into live `iris.cpf` on every IRIS start. **File is also live-monitored** while running and re-merged on change. | Idempotent merges only. Live-monitor behavior is surprising — edits to the file from the host apply immediately. |
| `ISC_PACKAGE_INSTANCENAME` | `IRIS` | Logical instance name. | Set at image build time; baked into the binary. |
| `ISC_PACKAGE_INSTALLDIR` | `/usr/irissys` | Install root. | — |
| `ISC_PACKAGE_IRISUSER` | `irisowner` | Owner of install tree (UID 51773). | Used in `chown` patterns; pair with `ISC_PACKAGE_IRISGROUP`. |
| `ISC_PACKAGE_IRISGROUP` | `irisowner` | Group counterpart (GID 51773). | — |
| `ISC_PACKAGE_MGRUSER` | `irisowner` | OS user that owns `mgr/` and runs background daemons. | — |
| `ISC_PACKAGE_MGRGROUP` | `irisowner` | Group counterpart for mgr. | — |
| `IRISSYS` | `/home/irisowner/irissys` | Registry / instance metadata. | — |
| `PYTHONPATH` | `/usr/irissys/mgr/python` | Path used by Embedded Python. | — |
| `IRIS_USERNAME` | unset | Community-image-only: auto-create this IRIS user at first boot. | First-boot only. Ignored if durable %SYS already initialized. |
| `IRIS_PASSWORD` | unset | Password for the auto-created user. | First-boot only. |
| `IRIS_NAMESPACE` | unset | Namespace to auto-create at first boot (with code/data DBs + CSP app). | First-boot only. |
| `LD_LIBRARY_PATH` | preset to `/usr/irissys/bin` | Loader path for IRIS libs. | Augment, never replace, or callouts break. |

---

## 3. Inside-container CLI — the `iris` command

`iris <subcommand> <instname> [args]` where `<instname>` is `IRIS`.
Trailing `quietly` suppresses confirmations; trailing `restart` on
`stop` means stop-then-start.

### 3.1 Lifecycle

| Subcommand | Signature | Behavior | Read/Write | State required |
|---|---|---|---|---|
| `start` | `iris start IRIS [<cpf>] [nostu] [quietly]` | Allocates SHM, starts AWDs, runs `^STU`. Optional CPF path overrides `<install>/mgr/iris.cpf`; `nostu` skips the startup routine. | Mutating | Stopped |
| `stop` | `iris stop IRIS [nofailover] [quietly] [restart]` | Triggers `SHUTDOWN^%SS`. Default 5-min timeout. `nofailover` prevents mirror failover. Trailing `restart` makes it a stop-then-start. | Mutating | Running |
| `force` | `iris force IRIS` | Last-resort kill — bypasses graceful path. Recovery runs on next `start`. | Mutating | Unresponsive |
| `stopstart` | `iris stopstart IRIS [args]` | Stop then start. Inherits `iris stop` flags. | Mutating | Running |
| `kill` | `iris kill IRIS` | Force-terminate processes from outside (rare; use after `force` fails). Help-only. | Mutating | Broken |

### 3.2 Discovery

| Subcommand | Signature | Behavior | Read/Write |
|---|---|---|---|
| `list` | `iris list [<inst>]` | Per-instance summary; truncated at 78 chars with trailing `~`. | Read-only |
| `all` | `iris all` | Full per-instance summary; `^`-separated, lines wrap. | Read-only |
| `qlist` | `iris qlist [<inst>]` | Machine-parseable: one line per instance, `^`-separated, no wrap. **Use this in scripts** to detect `running`/`down`/`in transition`. | Read-only |
| `qstop` | `iris qstop IRIS` | Quiet stop. Help-only. Equivalent to `iris stop IRIS quietly`. | Mutating |

`iris qlist` output fields (`^`-separated):
`<name> ^ <directory> ^ <version> ^ <state> ^ <port> ^ <web-port> ^ <jdbc-port> ^ <key-status>`

### 3.3 Interactive shells

| Subcommand | Signature | Behavior | LU cost |
|---|---|---|---|
| `session` | `iris session IRIS [-U <ns>] [-B] ["<cmd>"]` | UNIX/Linux ObjectScript shell (canonical for scripting). `-U` selects starting namespace. Trailing quoted ObjectScript executes non-interactively. | 1 LU per call |
| `terminal` | `iris terminal IRIS [<args>]` | Interactive shell, all platforms. UNIX shells out to `irisuxsession`. | 1 LU |
| `console` | `iris console IRIS` | Programmer-mode shell with no `$Principal`. Recovery path when `terminal`/`session` won't start (e.g. LU exhaustion). | does **not** consume a normal LU in some failure modes |

**Heredoc pattern (canonical):**
```sh
docker exec -i foia iris session IRIS -U %SYS <<'END'
ZN "USER"
W !,$ZV,!
HALT
END
```
- Heredoc must end with `HALT` (or `H`); `QUIT` only exits the current
  stack frame and the session lingers, hanging the `docker exec`.
- Use `<<'END'` (single-quoted) so `$SYSTEM`/`$P` aren't shell-expanded.
- Add `-i` (not `-it`) for non-interactive piping; `-it` works only
  with a real TTY.

**Single-line variant:**
```sh
docker exec foia iris session IRIS -U %SYS \
    'W ##class(%SYSTEM.License).LUAvailable(),!  H'
```

### 3.4 SQL

| Subcommand | Signature | Behavior | Notes |
|---|---|---|---|
| `runsql` | `iris runsql IRIS [<ns>] [<sql-or-path>]` | Run SQL inline or from a file in a chosen namespace. Underlying API: `$SYSTEM.SQL.Schema.ImportDDL`. Help-only beyond `<namespace>`. | Mutating; running instance |
| `sql` | (alias on some versions) | Synonym for `runsql` in some versions. | — |

### 3.5 Database / journal / config

| Subcommand | Signature | Behavior |
|---|---|---|
| `merge` | `iris merge IRIS [<merge-file>] [<target-cpf>]` | Apply a partial CPF (Configuration Merge). Both paths optional — fall back to `ISC_CPF_MERGE_FILE`/`ISC_CPF_TARGET`. **Only safe way to change CPF in a container** — manual edits to `iris.cpf` while running can be overwritten on shutdown. |
| `journal` | `iris journal IRIS ...` | Wraps `^JOURNAL` / `^JRNRESTO`. Sub-flags help-only. |
| `dbsize` | `iris dbsize IRIS` | Estimate backup size. Wraps `^DBSIZE`. Output is 7 caret-separated numbers per database. |
| `set` | `iris set IRIS ...` | Set instance-level CPF values. Help-only. |
| `fix` | `iris fix IRIS` | Repair instance whose registry/CPF is corrupt. Help-only. Stopped only. |
| `setssl` | `iris setssl IRIS` | Configure superserver TLS. Help-only. |

### 3.6 Diagnostics / verification

| Subcommand | Signature | Behavior |
|---|---|---|
| `stats` | `iris stats IRIS [<irisstat-flags>]` | Front-end to `irisstat`. Accepts the same single-letter flags (see §4). |
| `verify` | `iris verify IRIS` | Verify install/instance integrity. Help-only beyond name. |

### 3.7 Help

| Subcommand | Behavior |
|---|---|
| `iris help` | Authoritative live inventory of every subcommand. Output also written to `<install>/Help/IRISHelp.html`. **Always cross-check against this** for help-only sub-flags. |

---

## 4. Inside-container CLI — adjacent tools

| Tool | Path | Type | Purpose |
|---|---|---|---|
| `iris` | `/usr/irissys/bin/iris` | Wrapper script | Master front-end (§3). |
| `irismaster` | `/usr/irissys/bin/irismaster` | Daemon | Started by `iris start`; not invoked directly. |
| `irisuxsession` | `/usr/irissys/bin/irisuxsession` | Binary | UNIX terminal/session backend invoked by `iris terminal` / `iris session`. |
| `irissession` (legacy) | varies | Wrapper | Pre-2018 alias still piped into by some community Dockerfiles; modern equivalent is `iris session`. |
| `irisstat` | `/usr/irissys/bin/irisstat` | Binary | Diagnostics (§4.1). |
| `cstat` | `/usr/irissys/bin/cstat` (symlink, legacy) | — | Legacy Caché-era name; typically a symlink to `irisstat` for backwards compat. Verify with `ls -l /usr/irissys/bin/cstat`. |
| `irissqlcli` | not bundled | Third-party | Interactive SQL REPL with autocomplete; install with `pip install irissqlcli`. |
| `iris-main` | `/iris-main` | Entrypoint | Wrapper (§1). |
| `irisHealth.sh` | `/irisHealth.sh` | Script | Docker `HEALTHCHECK` probe. |

### 4.1 `irisstat` flags

`irisstat` attaches to IRIS shared memory and dumps internal tables.
Lowercase flags are read-only / non-invasive; **uppercase flags can
mutate shared memory** — use with care.

| Flag | Meaning | Flag | Meaning |
|---|---|---|---|
| `-a` | All | `-B` | Blocks in GBFSPECQ |
| `-b` | Bits | `-C` | Inter-job comms |
| `-c` | Counters | `-D` | Sample block collisions |
| `-d` | Dump processes | `-E` | Cluster status |
| `-e` | Error log | `-G` | Global buffers (BDB) |
| `-f` | Global module flags | `-H` | Global buffers (SFN/BLK) |
| `-g` | `^GLOSTAT` info | `-I` | Incremental backups |
| `-h` | Usage help | `-L` | License (LU usage) |
| `-j` | Journal | `-M` | Mailbox log |
| `-k` | Prefetch daemons | `-N` | ECP |
| `-l` | LRU global buffers | `-R` | Routine buffers |
| `-m` | GFILETAB | `-S` | Hang info |
| `-n` | Network | `-T` | In-memory tables |
| `-o` | Clear irisstat | `-V` | Process memory variables |
| `-p` | Processes | `-W` | Perform thaw (mutating) |
| `-q` | Hibernation semaphores | `-X` | Device translation table |
| `-s` | irisstat exe directory | | |
| `-t` | Run irisstat in loop | | |
| `-u` | Locks | | |
| `-v` | Check versions | | |
| `-w` | Write daemon queues | | |

`irisstat -L` is the canonical answer to "how many LUs am I burning
right now?" — load-bearing on Community Edition. The HTTP equivalent
is the metrics endpoint (§7).

---

## 5. Network protocol surface

| Port | Protocol | Default state | Carries |
|---|---|---|---|
| **1972/tcp** | InterSystems Superserver (proprietary binary) | Listening | ODBC, JDBC (`jdbc:IRIS://host:1972/NAMESPACE`), .NET / Python / Node IRIS Native SDKs, the Atelier wire protocol, `%Net.Remote.*` Java/.NET object gateway, ECP (mirror/sharding), Studio. |
| **52773/tcp** | HTTP (Web Gateway private Apache) | Listening, plain HTTP | All `/csp/*` and `/api/*` traffic, Management Portal. **HTTPS is not enabled by default.** |
| 53773/tcp | xDBC private | Exposed but not used by default | xDBC server fallback (Community typically uses 1972). |
| 2188/tcp | ISCAgent | Exposed but not used | HA mirror agent; only relevant in mirrored deployments. |
| 4002 | License Server (label-default) | Not exposed | Cluster license arbitration. |
| 54773/tcp | Internal | Exposed but not used | — |
| Telnet | Disabled | n/a | Not built into the Linux/Docker image. |
| SSH | Not present | n/a | No sshd. Use `docker exec`. |

**SuperServer port history.** Pre-2020.3 images defaulted to 51773.
Current `latest-em`/`latest-cd` tags use **1972**. Old client
connection strings still pointing at 51773 silently time out.

**Default credentials.** `_SYSTEM` / `SYS`. Forced password change on
first portal login. Built-in additional accounts: `Admin`,
`SuperUser`, `CSPSystem`. Change at first start via `--password-file`,
`IRIS_PASSWORD`, or the portal at `/csp/sys/sec/UtilSysUsers.csp`.

---

## 6. HTTP API surface (port 52773)

All paths are served by the IRIS Web Gateway over plain HTTP by default.
Live status against this image (`200`, `401`, or `404`) is annotated
where probed.

### 6.1 `/api/monitor/*` — observability

| Path | Status here | Auth | Format | Purpose |
|---|---|---|---|---|
| `/api/monitor/metrics` | **200** unauthenticated | configurable | Prometheus / OpenMetrics text | All instance metrics (107 counters in 2026.1 — see §7). Compatible with Prometheus/Grafana scraping. |
| `/api/monitor/alerts` | **200** unauthenticated | configurable | JSON | All system alerts since last scrape (mirrors `alerts.log`). |
| `/api/monitor/interop/current/interfaces` | password required | `%Admin Manage` | JSON | Live count of unique interop interfaces. |
| `/api/monitor/interop/historical/interfaces` | password required | `%Admin Manage` | JSON | Same, time-windowed. |
| `/api/monitor` (bare) | 404 | — | — | Not a route. |

> **Note on auth.** The `/api/monitor` web app is shipped with
> password auth on, but in this Community image it has been left
> unauthenticated (probed: 200 with no creds). The `/api/monitor/*`
> family is the cleanest programmatic surface for AI agents — no auth
> dance, machine-parseable output.

### 6.2 `/api/atelier/*` — source code CRUD

| Path | Auth | Purpose |
|---|---|---|
| `/api/atelier/` | password (`%Developer`) | Server self-description: `GetServer` returns API version, namespaces, server info. |
| `/api/atelier/v1/`, `/api/atelier/v2/` … `/api/atelier/v6/` | password | Source-code file CRUD. Used by the official VS Code ObjectScript extension. Endpoints include `GetDocNames`, `GetDoc`, `GetDocs`, `Index`, `PutDoc`, `DeleteDoc`, `Compile`, `Search`, `WorkMgr` queries. ETag/`If-None-Match` supported on `GetDoc`. |

In this image (2026.1) `/api/atelier/v6` returns `401` — version 6 is
present and auth-gated. Always include the version segment.

### 6.3 `/api/mgmnt/*` — REST app management

| Path | Auth | Purpose |
|---|---|---|
| `/api/mgmnt/` | password (`%Admin Manage`) | Legacy: list REST-enabled web apps in all namespaces. (Bare path returned 404 here; query via the v2 form below.) |
| `/api/mgmnt/v2/` | password | All REST services across namespaces. |
| `/api/mgmnt/v2/{ns}/` | password | REST services in a namespace. |
| `GET /api/mgmnt/v2/{ns}/{app}/` | password | OpenAPI 2.0 (Swagger) spec for that REST app — built-in spec discovery for any IRIS REST service. |
| `POST /api/mgmnt/v2/{ns}/{app}` | password | Generate spec-first scaffolding from a posted Swagger 2.0 doc. |

### 6.4 `/csp/sys/*` — Management Portal

High-value pages for programmatic / AI use:

| Path | Purpose |
|---|---|
| `/csp/sys/UtilHome.csp` | Portal home. |
| `/csp/sys/op/UtilSysLicenseUse.csp` | License Use page (live LU breakdown by user/connection). |
| `/csp/sys/mgr/UtilSysLicense.csp` | License Key — view/upload `iris.key`. |
| `/csp/sys/mgr/UtilSysNamespaces.csp` | Namespace list / create / configure. |
| `/csp/sys/sec/UtilSysUsers.csp` | Users — list, edit, password reset. |
| `/csp/sys/sec/...` | Roles, services, applications, SSL/TLS configs. |
| `/csp/sys/op/UtilSysJournals.csp` | Journal viewer / settings. |
| `/csp/sys/exp/UtilSysOptions.csp` | System Explorer landing — globals/classes/routines/SQL. |
| `/csp/documatic/%CSP.Documatic.cls` | Class reference browser. The most reliable way to discover every REST route — search `%Api.*` and `%CSP.REST` subclasses. |
| `/csp/{namespace}/...` | Per-namespace web app — application code, REST dispatch classes. |

---

## 7. Live metrics inventory (`/api/monitor/metrics`)

107 counters in 2026.1, grouped here for navigability. All have
`iris_` prefix; types are mostly `gauge`. Probe with
`curl http://localhost:52773/api/monitor/metrics | grep '^# HELP'`
for live HELP strings.

| Category | Counters |
|---|---|
| **License** | `license_consumed`, `license_available`, `license_percent_used`, `license_days_remaining` |
| **System / health** | `system_state`, `system_info`, `system_alerts`, `system_alerts_log`, `system_alerts_new`, `cpu_usage`, `cpu_pct`, `phys_mem_percent_used`, `page_space_percent_used`, `disk_percent_full`, `directory_space` |
| **CSP / Web Gateway** | `csp_activity`, `csp_actual_connections`, `csp_in_use_connections`, `csp_private_connections`, `csp_sessions`, `csp_gateway_latency` |
| **Database** | `db_size_mb`, `db_max_size_mb`, `db_free_space`, `db_expansion_size_mb`, `db_file_limit_percent`, `db_latency`, `cache_efficiency` |
| **Globals** | `glo_ref_per_sec`, `glo_ref_rem_per_sec`, `glo_update_per_sec`, `glo_update_rem_per_sec`, `glo_seize_per_sec`, `glo_a_seize_per_sec`, `glo_n_seize_per_sec` |
| **Routines** | `rtn_count_by_ns`, `rtn_load_per_sec`, `rtn_load_rem_per_sec`, `rtn_call_local_per_sec`, `rtn_call_remote_per_sec`, `rtn_call_miss_per_sec`, `rtn_seize_per_sec`, `rtn_a_seize_per_sec` |
| **Objects** | `obj_load_per_sec`, `obj_new_per_sec`, `obj_del_per_sec`, `obj_hit_per_sec`, `obj_miss_per_sec`, `obj_seize_per_sec`, `obj_a_seize_per_sec` |
| **Resources / locks** | `res_seize`, `res_a_seize`, `res_n_seize` |
| **Processes** | `process`, `process_count`, `process_commands`, `process_glo_refs`, `process_jrn_entries`, `process_phys_reads`, `process_block_allocs`, `process_block_writes`, `process_ppg_size_mb` |
| **Journal** | `jrn_size`, `jrn_free_space`, `jrn_block_per_sec`, `jrn_entry_per_sec`, `iju_count`, `iju_lock` |
| **Write daemon** | `wd_phase`, `wd_pass`, `wd_cycle_time`, `wd_condition`, `wd_sleep`, `wd_suspended`, `wd_buffer_write`, `wd_buffer_redirty`, `wd_size_write`, `wd_temp_queue`, `wd_temp_write`, `wd_proc_in_global`, `wd_write_time`, `wdwij_time`, `wij_writes_per_sec` |
| **SQL** | `sql_commands_per_second`, `sql_queries_per_second`, `sql_queries_avg_runtime`, `sql_queries_avg_runtime_std_dev`, `sql_row_count_per_second`, `cached_query_by_ns` |
| **Work queue manager** | `wqm_active_worker_jobs`, `wqm_max_active_worker_jobs`, `wqm_waiting_worker_jobs`, `wqm_max_work_queue_depth`, `wqm_commands_per_sec`, `wqm_globals_per_sec` |
| **ECP** | `ecp_conn`, `ecp_conn_max`, `ecps_conn`, `ecps_conn_max` |
| **Mirroring** | `mirror_member_type` |
| **Shared memory heap** | `smh_total`, `smh_used`, `smh_available`, `smh_percent_full`, `smh_total_percent_full` |
| **Phys I/O** | `phys_reads_per_sec`, `phys_writes_per_sec`, `log_reads_per_sec` |
| **Transactions** | `trans_open_count`, `trans_open_secs`, `trans_open_secs_max` |
| **SAM (System Alert & Monitoring)** | `sam_get_db_sensors_seconds`, `sam_get_jrn_sensors_seconds`, `sam_get_sql_sensors_seconds`, `sam_get_interop_sensors_seconds`, `sam_get_wqm_sensors_seconds` |

---

## 8. Filesystem surface inside the container

| Path | Owner | Contents |
|---|---|---|
| `/usr/irissys/` | `irisowner:irisowner` | IRIS install root. |
| `/usr/irissys/bin/` | irisowner | Binaries: `iris`, `irismaster`, `irisuxsession`, `irisstat`, `irisdb`, shared libs. |
| `/usr/irissys/mgr/` | irisowner | Manager directory: `IRIS.DAT` for `IRISSYS`, `iris.lck`, `iris.cpf` (live config), `messages.log`, `IRIS.WIJ`, `alerts.log`, `audit.log`, `stream/`, per-DB subfolders (`iris/`, `irissecurity/`, `iristemp/`, `irisaudit/`, `irismetrics/`, `user/`). |
| `/usr/irissys/mgr/iris.cpf` | irisowner | Live configuration parameter file. Source of truth at runtime. |
| `/usr/irissys/mgr/messages.log` | irisowner | Primary instance log ("console log"). Path overridable in `iris.cpf` `[config] ConsoleFile=…`. |
| `/usr/irissys/mgr/journal/` | irisowner | Rolling journal files (`YYYYMMDD.NNN`). |
| `/usr/irissys/mgr/IRIS.WIJ` | irisowner | Write Image Journal. |
| `/usr/irissys/dev/` | irisowner | Client SDKs in image: `dev/java/lib/1.8`, `dev/dotnet/bin/net5.0`, `dev/nodejs/intersystems-iris-native`, `dev/python`. |
| `/usr/irissys/csp/` | irisowner | CSP web-app static + class artifacts. |
| `/home/irisowner/` | irisowner | Home of UID 51773; working dir. Contains `iris-main.log`. |
| `/home/irisowner/irissys/` | irisowner | Registry / instance metadata. |
| `/iris-main` | root, 0755 | Entrypoint wrapper. |
| `/irisHealth.sh` | root | Healthcheck script. |
| `/tini` | root | Init shim used as PID 1. |

**Durable %SYS interaction with bind mounts.** When
`ISC_DATA_DIRECTORY=/durable/iris` and `/durable` is a bind/volume:
- First start: IRIS clones `mgr/` and related state into
  `/durable/iris/mgr/`, rewrites pointers; the in-image
  `/usr/irissys/mgr/` is no longer used for live data.
- Subsequent starts (including from a newer image version): IRIS
  reuses `/durable/iris/mgr/` as-is — enabling zero-loss instance
  migration across image upgrades.
- Host directory must be `chown 51773:51773` *before* `docker run`.

---

## 9. Common patterns for programmatic interaction

### 9.1 Non-interactive ObjectScript via heredoc

```sh
docker exec -i foia iris session IRIS -U %SYS <<'END'
ZN "USER"
W !,$ZV,!
HALT
END
```
Always end with `HALT` (not `QUIT`) and use single-quoted heredoc tag.

### 9.2 Single-line ObjectScript

```sh
docker exec foia iris session IRIS -U %SYS \
    'W ##class(%SYSTEM.License).LUAvailable(),!  H'
```

### 9.3 Copy-then-execute routines

```sh
docker cp myroutine.m foia:/tmp/
docker exec -i foia iris session IRIS -U %SYS <<'END'
ZR
S F="/tmp/myroutine.m"
O F U F ZL ZS myroutine C F
D ^myroutine
HALT
END
```

### 9.4 SQL import

```sh
docker cp schema.sql foia:/tmp/
docker exec foia iris session IRIS -U USER \
    'D $SYSTEM.SQL.Schema.ImportDDL("/tmp/schema.sql",.log)  H'
```

### 9.5 Host-network helper for HTTP probes

When the host's curl is sandbox-blocked, route through a helper:

```sh
docker run --rm --network host alpine sh -c \
    'wget -qO- http://localhost:52773/api/monitor/metrics' \
    | grep ^iris_license_
```

### 9.6 Read mode-700 host volumes (UID 51773)

```sh
docker run --rm --user 0 -v ~/data/foia-iris:/data:ro alpine \
    tail -n 200 /data/mgr/messages.log
```

### 9.7 Inspect the image without executing IRIS

```sh
docker run --rm --entrypoint sh foia:latest -c \
    'ls /usr/irissys/bin/ | head'
```
Skips the `iris-main` entrypoint, doesn't start IRIS, doesn't consume LU.

---

## 10. Gotchas

1. **UID 51773 permissions are the #1 failure mode.** Any host
   directory bind-mounted to a path used as `ISC_DATA_DIRECTORY` (or
   anywhere IRIS writes) must be `chown -R 51773:51773` before
   `docker run`. Without it IRIS aborts at startup.
2. **`ISC_DATA_DIRECTORY` without a matching `--volume` aborts startup.**
3. **NFS-backed volumes are unsupported** for IRIS data — use local
   block storage.
4. **Community Edition LU cap.** This image's `iris_license_*` metrics
   show an 8-LU cap. Steady-state idle (post-`^ZSTU`, listeners up,
   no shells) is ~1 LU. Each `iris session` adds 1 LU.
5. **`HALT` vs `QUIT`** in scripted sessions — `QUIT` only exits the
   current stack frame; `HALT` (or `H`) is what actually exits the
   IRIS process and unblocks the docker exec.
6. **Default credentials `_SYSTEM` / `SYS`** are flagged "expired" at
   first login. For headless first-boot, use `--password-file`.
7. **SuperServer port changed in 2020.3** from 51773 to **1972**.
   Old connection strings silently time out.
8. **No HTTPS by default on 52773.** All Mgmt Portal and `/api/*`
   traffic is plain HTTP. Front with a reverse proxy for non-localhost.
9. **`ISC_CPF_MERGE_FILE` is live-monitored** — host-side edits to
   the file get re-merged into `iris.cpf` while the container runs.
10. **First-boot env vars only.** `IRIS_USERNAME` /
    `IRIS_PASSWORD` / `IRIS_NAMESPACE` apply only on first boot;
    once durable %SYS exists they are ignored.
11. **`CAP_SETUID` / `CAP_SETGID` required.** Restrictive Kubernetes
    `securityContext: capabilities: drop: ["ALL"]` breaks startup
    unless paired with `--check-caps false`.
12. **`docker stop -t 10` may be too short** — graceful shutdown
    can need >10s on a busy instance. Prefer `-t 60`.
13. **No `iris-startup-script.sh` convention exists** in the official
    image. Hooks are `--before` / `--after` flags to `iris-main`.
14. **`/api/atelier` is unversioned at the root** — always include
    `/v1/`, `/v2/`, …, `/v6/`. Probing the bare path returns 404.
15. **`messages.log` location is overridable** via `iris.cpf`
    `[config] ConsoleFile=…`. If you can't find it at the default,
    check the CPF.
16. **Manual `iris.cpf` edits are fragile.** The active in-memory
    copy can overwrite hand-edits at certain shutdown paths. Use
    `iris merge` instead.
17. **`iris stop` default timeout is 5 minutes.** Long-running
    Ensemble productions can block this — stop business hosts first.
18. **Documatic at `/csp/documatic/%CSP.Documatic.cls`** is the most
    reliable surface for discovering all REST routes — search
    `%Api.*` and `%CSP.REST` subclasses; their `XData UrlMap` is
    the authoritative route table.

---

## Sources

### Official documentation

- [Manage InterSystems IRIS Instances: The iris Command](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_using_instance)
- [Running InterSystems Products in Containers (ADOCK)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ADOCK)
- [IRIS Basics: Run a Container (AFL_containers)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=AFL_containers)
- [Managing IRIS on UNIX/Linux/macOS](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_using_unix)
- [Monitoring IRIS via REST (GCM_rest)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GCM_rest)
- [Source Code File REST API Reference (GSCF_ref)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSCF_ref)
- [/api/mgmnt/ API Endpoints (GREST_reference)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GREST_reference)
- [Managing Superservers (GSA_manage_superserver)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_manage_superserver)
- [Port Numbers (GIEMISC_ports)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GIEMISC_ports)
- [Installation Directory (GIEMISC_defaultdir)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GIEMISC_defaultdir)
- [Monitoring with irisstat (GCM_irisstat)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GCM_irisstat)
- [Using the Management Portal (GSA_using_portal)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSA_using_portal)
- [Documatic %Api.Monitor](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?LIBRARY=%25SYS&CLASSNAME=%25Api.Monitor)

### Community / supplementary

- [hub.docker.com — intersystems/iris-community](https://hub.docker.com/r/intersystems/iris-community)
- [SuperServer port change 51773→1972](https://community.intersystems.com/post/superserver-port-change-51773-1972-20203)
- [Launching IRIS Community Edition with env vars](https://community.intersystems.com/post/launching-intersystems-iris-community-edition-docker-image-user-password-and-namespace)
- [Build IRIS image with cpf merge](https://community.intersystems.com/post/build-iris-image-cpf-merge)
- [Running IRIS for Health with durable %SYS](https://community.intersystems.com/post/running-iris-health-docker-container-durable-sys-volume)
- [IRISSTAT Options Cheat Sheet](https://community.intersystems.com/post/irisstat-options-cheat-sheet)
- [Gracefully shutting down IRIS without terminal access](https://community.intersystems.com/post/gracefully-shutting-down-iris-without-terminal-access-nix-flavor)
- [Welcome irissqlcli](https://community.intersystems.com/post/welcome-irissqlcli-advanced-terminal-iris-sql)
- [iris-docker-dev-kit/irissession.sh](https://github.com/intersystems-community/iris-docker-dev-kit/blob/master/irissession.sh)

### Live-image inspection

Image inspect (`docker image inspect foia:latest`), endpoint probes
on 2026-05-03 against build `2026.1.0.234.1com`.
