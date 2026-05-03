"""`irisctl start/stop/restart/recreate` — container lifecycle.

The mutating Phase-4 commands. `start` and `stop` are idempotent;
`restart` is `stop` + `start`. `recreate` (the destructive form) is
gated behind `--yes` and reuses the host volume so data survives.
"""

from __future__ import annotations

from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    container_exists,
    container_state,
    remove_container,
    start_container,
    stop_container,
    wait_for_tcp,
)
from irisctl.output import ErrorCode, error_envelope, success_envelope


def _expected_listeners(profile: Profile) -> list[int]:
    return [
        profile.superserver_port,
        profile.web_port,
        profile.rpc_port,
        profile.vistalink_port,
    ]


# ----------------- start -----------------


def start_run(profile: Profile, *, wait_timeout: float = 60.0) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "start",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
            hint="run `irisctl recreate` to bootstrap from the volume",
        )

    state = container_state(profile.container)
    if state["running"]:
        listeners = wait_for_tcp(profile.host, _expected_listeners(profile),
                                  timeout=wait_timeout)
        return success_envelope("start", {
            "container": profile.container,
            "already_running": True,
            "listeners": listeners,
        })

    try:
        start_container(profile.container)
    except DockerError as e:
        return error_envelope("start", code=ErrorCode.DOCKER_ERROR, message=str(e))

    listeners = wait_for_tcp(profile.host, _expected_listeners(profile),
                              timeout=wait_timeout)
    warnings: list[str] = []
    not_up = [p for p, ok in listeners.items() if not ok]
    if not_up:
        warnings.append(
            f"listener(s) not reachable after {wait_timeout}s: {sorted(not_up)}"
        )
    return success_envelope("start", {
        "container": profile.container,
        "already_running": False,
        "listeners": listeners,
    }, warnings=warnings)


# ----------------- stop -----------------


def stop_run(profile: Profile, *, timeout: int = 60) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "stop",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    state = container_state(profile.container)
    if not state["running"]:
        return success_envelope("stop", {
            "container": profile.container,
            "was_running": False,
        })

    try:
        stop_container(profile.container, timeout=timeout)
    except DockerError as e:
        return error_envelope("stop", code=ErrorCode.DOCKER_ERROR, message=str(e))

    return success_envelope("stop", {
        "container": profile.container,
        "was_running": True,
        "graceful_timeout_s": timeout,
    })


# ----------------- restart -----------------


def restart_run(
    profile: Profile,
    *,
    timeout: int = 60,
    wait_timeout: float = 60.0,
) -> dict[str, Any]:
    stop_env = stop_run(profile, timeout=timeout)
    if not stop_env["ok"]:
        return {**stop_env, "command": "restart"}

    start_env = start_run(profile, wait_timeout=wait_timeout)
    if not start_env["ok"]:
        return {**start_env, "command": "restart"}

    return success_envelope("restart", {
        "container": profile.container,
        "stopped": stop_env["data"].get("was_running", False),
        "listeners": start_env["data"]["listeners"],
    }, warnings=stop_env.get("warnings", []) + start_env.get("warnings", []))


# ----------------- recreate -----------------


def recreate_run(
    profile: Profile,
    *,
    image: str,
    yes: bool = False,
    dry_run: bool = False,
    wait_timeout: float = 90.0,
) -> dict[str, Any]:
    """Stop + remove the container, then `docker run` from the host volume."""
    argv = _docker_run_argv(profile, image=image)

    if dry_run:
        return success_envelope("recreate", {
            "container": profile.container,
            "image": image,
            "argv": argv,
            "dry_run": True,
        })

    if not yes:
        return error_envelope(
            "recreate",
            code=ErrorCode.USAGE,
            message=("recreate is destructive (rm + run). "
                     "Pass --yes to confirm, or --dry-run to inspect."),
            hint="data survives via the host bind mount; this only "
                 "rebuilds the container layer",
        )

    # Stop + remove if it exists
    if container_exists(profile.container):
        try:
            state = container_state(profile.container)
            if state["running"]:
                stop_container(profile.container, timeout=60)
            remove_container(profile.container, force=False)
        except DockerError as e:
            return error_envelope(
                "recreate", code=ErrorCode.DOCKER_ERROR, message=str(e),
            )

    # Run fresh
    from irisctl.docker_api import _run as _docker_run  # noqa: PLC0415
    try:
        _docker_run(argv, timeout=120)
    except DockerError as e:
        return error_envelope("recreate", code=ErrorCode.DOCKER_ERROR, message=str(e))

    listeners = wait_for_tcp(profile.host, _expected_listeners(profile),
                              timeout=wait_timeout)
    return success_envelope("recreate", {
        "container": profile.container,
        "image": image,
        "listeners": listeners,
    })


def _docker_run_argv(profile: Profile, *, image: str) -> list[str]:
    """Recipe from INSTALL_GUIDE.md §8 — restore-from-volume."""
    data_dir = str(profile.data_dir)
    return [
        "docker", "run", "--name", profile.container, "-d",
        "-v", f"{data_dir}/mgr:/usr/irissys/mgr",
        "-v", f"{data_dir}/iris.cpf:/usr/irissys/iris.cpf",
        "-p", f"{profile.superserver_port}:1972",
        "-p", f"{profile.web_port}:52773",
        "-p", f"{profile.rpc_port}:9430",
        "-p", f"{profile.vistalink_port}:8001",
        image,
    ]
