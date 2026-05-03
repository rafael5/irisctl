"""`irisctl ports` — per-listener reachability check.

For each known IRIS listener (superserver / web / rpc_broker / vistalink)
report container port, mapped host port, and TCP reachability.
"""

from __future__ import annotations

import socket
from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    container_exists,
    list_published_ports,
)
from irisctl.output import ErrorCode, error_envelope, success_envelope


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "ports",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )
    try:
        published = list_published_ports(profile.container)
    except DockerError as e:
        return error_envelope("ports", code=ErrorCode.DOCKER_ERROR, message=str(e))

    expected = {
        profile.superserver_port: "superserver",
        profile.web_port: "web",
        profile.rpc_port: "rpc_broker",
        profile.vistalink_port: "vistalink",
    }

    rows: list[dict[str, Any]] = []
    by_host: dict[int, dict[str, Any]] = {}
    for binding in published:
        if binding.get("host_port") is not None:
            by_host[binding["host_port"]] = binding

    for port, role in expected.items():
        entry: dict[str, Any] | None = by_host.get(port)
        if entry is None:
            rows.append({
                "role": role,
                "container_port": None,
                "host_port": port,
                "reachable": False,
                "note": "not published by container",
            })
            continue
        rows.append({
            "role": role,
            "container_port": entry.get("container_port"),
            "host_port": port,
            "reachable": _tcp_open(profile.host, port),
        })

    warnings = [
        f"{r['role']} ({r['host_port']}) not reachable"
        for r in rows if not r["reachable"]
    ]
    return success_envelope("ports", rows, warnings=warnings)
