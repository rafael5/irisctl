"""`irisctl status` — composite container + listener + license check.

Returns one structured snapshot covering everything an operator/AI
needs to know "is this instance healthy right now". Aggregates the
results of the cheaper subcommands.
"""

from __future__ import annotations

from typing import Any

from irisctl.commands import license as cmd_license
from irisctl.commands import ports as cmd_ports
from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    container_exists,
    container_state,
)
from irisctl.http_api import IrisHttpClient, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "status",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )
    try:
        cstate = container_state(profile.container)
    except DockerError as e:
        return error_envelope("status", code=ErrorCode.DOCKER_ERROR, message=str(e))

    # Reuse other commands for their data (drop into envelopes' data).
    ports_env = cmd_ports.run(profile)
    license_env = cmd_license.run(profile)

    listeners = ports_env["data"] if ports_env["ok"] else []
    license_data = license_env["data"] if license_env["ok"] else None

    # Pull system_state metric directly (cheap on top of license probe).
    system_state = _probe_system_state(profile)

    warnings: list[str] = []
    if not cstate["running"]:
        warnings.append("container not running")
    if cstate.get("health") == "unhealthy":
        warnings.append("docker healthcheck reports unhealthy "
                        "(known false-negative on Community LU saturation)")
    if not ports_env["ok"]:
        warnings.append(f"ports check failed: {ports_env['error']['message']}")
    if not license_env["ok"]:
        warnings.append(f"license check failed: {license_env['error']['message']}")
    if any(not row.get("reachable") for row in listeners):
        warnings.append("one or more listeners unreachable")

    return success_envelope("status", {
        "container": cstate,
        "listeners": listeners,
        "license": license_data,
        "system_state": system_state,
    }, warnings=warnings)


def _probe_system_state(profile: Profile) -> dict[str, Any] | None:
    try:
        client = IrisHttpClient(base_url=profile.web_base_url())
        metrics = client.metrics(prefix="iris_system_")
    except NetworkError:
        return None
    out: dict[str, Any] = {}
    for m in metrics:
        if m.name == "iris_system_state":
            out["state"] = m.value
        elif m.name == "iris_system_alerts":
            out["alerts"] = m.value
        elif m.name == "iris_system_alerts_new":
            out["alerts_new"] = m.value
    return out or None
