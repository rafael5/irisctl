"""`irisctl which <op>` — explain the underlying command for an operation.

Debug / discovery aid for users (and AI agents) who want to know what
each subcommand actually does at the docker / HTTP / iris-session
layer. Templates substitute the active profile's values so the printed
command is copy-pasteable.
"""

from __future__ import annotations

from typing import Any

from irisctl.config import Profile
from irisctl.output import ErrorCode, error_envelope, success_envelope

# op -> (mechanism, underlying-command-template, lu_cost, notes)
# Templates may reference {host}, {web_port}, {container}, {data_dir}.
OPERATIONS: dict[str, dict[str, Any]] = {
    # Phase 1 — read-only floor (no LU)
    "status": {
        "mechanism": "docker inspect + TCP probe + /api/monitor/metrics",
        "underlying": "docker inspect {container}; "
                      "curl http://{host}:{web_port}/api/monitor/metrics",
        "lu_cost": 0,
    },
    "version": {
        "mechanism": "docker inspect (image labels)",
        "underlying": "docker inspect {container} | jq '.Config.Labels'",
        "lu_cost": 0,
    },
    "ports": {
        "mechanism": "docker inspect + host TCP probe",
        "underlying": "docker inspect {container} (ports) + connect({host},...)",
        "lu_cost": 0,
    },
    "logs": {
        "mechanism": "alpine helper container reads bind-mounted messages.log",
        "underlying": "docker run --rm --user 0 -v {data_dir}/mgr/messages.log:"
                      "{data_dir}/mgr/messages.log:ro alpine tail -nN ...",
        "lu_cost": 0,
    },
    "alerts": {
        "mechanism": "GET /api/monitor/alerts (unauth on Community image)",
        "underlying": "curl http://{host}:{web_port}/api/monitor/alerts",
        "lu_cost": 0,
    },
    "health": {
        "mechanism": "composite (status + ports + alerts) → green/yellow verdict",
        "underlying": "(see status, ports, alerts)",
        "lu_cost": 0,
    },
    "license": {
        "mechanism": "GET /api/monitor/metrics, filter iris_license_*",
        "underlying": "curl http://{host}:{web_port}/api/monitor/metrics "
                      "| grep ^iris_license_",
        "lu_cost": 0,
    },
    "metrics": {
        "mechanism": "GET /api/monitor/metrics + Prometheus parser",
        "underlying": "curl http://{host}:{web_port}/api/monitor/metrics",
        "lu_cost": 0,
    },
    # Phase 2 — execution (1 LU per call)
    "exec": {
        "mechanism": "docker exec -i + iris session heredoc (HALT-injected)",
        "underlying": "docker exec -i {container} iris session IRIS -U <ns> "
                      "<<'EOF' <script>\\nHALT\\nEOF",
        "lu_cost": 1,
    },
    "sql": {
        "mechanism": "iris session heredoc wrapping %SQL.Statement.%ExecDirect",
        "underlying": "docker exec -i {container} iris session IRIS -U <ns> "
                      "<<'EOF' DO ##class(%SQL.Statement).%ExecDirect... HALT EOF",
        "lu_cost": 1,
    },
    "shell": {
        "mechanism": "execvp into docker exec -it iris session",
        "underlying": "docker exec -it {container} iris session IRIS -U <ns>",
        "lu_cost": 1,
    },
    # Phase 3 — Atelier (auth-gated)
    "namespaces": {
        "mechanism": "GET /api/atelier/v6/ (Atelier GetServer)",
        "underlying": "curl -u user:pw http://{host}:{web_port}/api/atelier/v6/",
        "lu_cost": 0,
        "auth_required": True,
    },
    "source": {
        "mechanism": "Atelier doc CRUD over /api/atelier/v6/{ns}/...",
        "underlying": "curl -u user:pw -X GET|PUT|DELETE "
                      "http://{host}:{web_port}/api/atelier/v6/<ns>/doc/<doc>",
        "lu_cost": 0,
        "auth_required": True,
    },
    # Phase 4 — lifecycle + persistence
    "start": {
        "mechanism": "docker start + wait_for_tcp on listener ports",
        "underlying": "docker start {container}",
        "lu_cost": 0,
    },
    "stop": {
        "mechanism": "docker stop -t N (default 60)",
        "underlying": "docker stop -t 60 {container}",
        "lu_cost": 0,
    },
    "restart": {
        "mechanism": "stop + start (composite)",
        "underlying": "docker stop -t 60 {container} && docker start {container}",
        "lu_cost": 0,
    },
    "recreate": {
        "mechanism": "docker rm + docker run from host volume (--yes-gated)",
        "underlying": "docker rm -f {container}; docker run --name {container} "
                      "-d -v {data_dir}/mgr:/usr/irissys/mgr -v {data_dir}/iris.cpf:"
                      "/usr/irissys/iris.cpf -p 1972:1972 ... <image>",
        "lu_cost": 0,
        "destructive": True,
    },
    "backup": {
        "mechanism": "alpine helper tar of host bind volume",
        "underlying": "docker run --rm --user 0 -v {data_dir}:/data:ro "
                      "-v <out-dir>:/out alpine tar czf /out/<name>.tgz -C / data",
        "lu_cost": 0,
    },
    "restore": {
        "mechanism": "stop + wipe + untar + start (--yes-gated)",
        "underlying": "docker stop {container} && rm -rf {data_dir}/mgr && "
                      "tar xzf <backup.tgz> -C {data_dir} && docker start {container}",
        "lu_cost": 0,
        "destructive": True,
    },
    "config": {
        "mechanism": "alpine cat for show; docker cp + iris merge for merge",
        "underlying": "show: alpine cat {data_dir}/iris.cpf  |  "
                      "merge: docker cp <file> {container}:/tmp/m.cpf && "
                      "docker exec {container} iris merge IRIS /tmp/m.cpf",
        "lu_cost": 0,
    },
}


def _format(template: str, profile: Profile) -> str:
    return template.format(
        host=profile.host,
        web_port=profile.web_port,
        container=profile.container,
        data_dir=str(profile.data_dir),
    )


def describe(op: str, profile: Profile) -> dict[str, Any] | None:
    spec = OPERATIONS.get(op)
    if spec is None:
        return None
    rec: dict[str, Any] = {
        "op": op,
        "mechanism": spec["mechanism"],
        "underlying": _format(spec["underlying"], profile),
        "lu_cost": spec["lu_cost"],
    }
    if spec.get("auth_required"):
        rec["auth_required"] = True
    if spec.get("destructive"):
        rec["destructive"] = True
    if spec.get("lu_cost", 0) == 0:
        rec["no_lu"] = True
    return rec


def run(profile: Profile, *, op: str | None) -> dict[str, Any]:
    if op is None:
        rows = [describe(name, profile) for name in sorted(OPERATIONS)]
        return success_envelope("which", {
            "operations": [r for r in rows if r is not None],
            "count": len(OPERATIONS),
        })
    rec = describe(op, profile)
    if rec is None:
        return error_envelope(
            "which",
            code=ErrorCode.NOT_FOUND,
            message=f"unknown operation: {op!r}",
            hint=f"try one of: {', '.join(sorted(OPERATIONS))}",
        )
    return success_envelope("which", rec)
