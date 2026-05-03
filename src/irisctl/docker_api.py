"""Docker CLI wrapper.

Wraps `docker inspect` / `docker ps` / `docker run --rm --user 0` for
the read-only operations Phase 1 needs. Shells out to the docker
binary; no Python docker SDK dependency.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class DockerError(Exception):
    """docker CLI failed or returned no result for the given container."""


def _run(cmd: list[str], timeout: float = 15.0) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"timeout: {' '.join(cmd)}") from e
    except FileNotFoundError as e:
        raise DockerError("docker CLI not found on PATH") from e
    if res.returncode != 0:
        raise DockerError(
            f"{' '.join(cmd)}: exit {res.returncode}: "
            f"{res.stderr.strip() or res.stdout.strip()}"
        )
    return res.stdout


def container_exists(name: str) -> bool:
    out = _run([
        "docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"
    ])
    return name in out.split()


def inspect_container(name: str) -> dict[str, Any]:
    out = _run(["docker", "inspect", name])
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise DockerError(f"invalid JSON from docker inspect: {e}") from e
    if not data:
        raise DockerError(f"no inspect data for {name!r}")
    return data[0]


def container_state(name: str) -> dict[str, Any]:
    info = inspect_container(name)
    state = info.get("State", {})
    return {
        "status": state.get("Status", "unknown"),
        "running": bool(state.get("Running", False)),
        "health": (state.get("Health") or {}).get("Status", "none"),
        "started_at": state.get("StartedAt", ""),
        "exit_code": state.get("ExitCode"),
    }


def image_labels(name: str) -> dict[str, str]:
    info = inspect_container(name)
    return dict(info.get("Config", {}).get("Labels") or {})


def list_published_ports(name: str) -> list[dict[str, Any]]:
    """Return one row per (container_port, host_port) binding.

    Container ports without a host binding still appear (host_port=None).
    """
    info = inspect_container(name)
    out: list[dict[str, Any]] = []
    bindings = info.get("NetworkSettings", {}).get("Ports") or {}
    for cport, host_list in bindings.items():
        # cport like "1972/tcp"
        try:
            port_str, proto = cport.split("/", 1)
            cport_num = int(port_str)
        except ValueError:
            continue
        if not host_list:
            out.append({"container_port": cport_num, "host_port": None,
                        "proto": proto})
            continue
        seen_hosts: set[int] = set()
        for binding in host_list:
            hp = binding.get("HostPort")
            if hp is None:
                continue
            try:
                hp_num = int(hp)
            except (TypeError, ValueError):
                continue
            if hp_num in seen_hosts:
                continue
            seen_hosts.add(hp_num)
            out.append({"container_port": cport_num, "host_port": hp_num,
                        "proto": proto})
    return out


def tail_log_via_helper(host_path: str, tail: int = 200) -> str:
    """Tail a host file via a transient root-uid alpine container.

    Used to read mode-700 / UID-51773 host volumes (e.g. messages.log
    under ~/data/foia-iris/) without needing host root.
    """
    cmd = [
        "docker", "run", "--rm", "--user", "0",
        "-v", f"{host_path}:{host_path}:ro",
        "alpine", "tail", f"-n{tail}", host_path,
    ]
    return _run(cmd, timeout=30)
