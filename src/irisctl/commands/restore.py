"""`irisctl restore` — replace the host volume from a backup tarball.

Sequence (per INSTALL_GUIDE.md §8 "Restoring after teardown"):
  1. `docker stop` the container if running
  2. wipe the data dir via a root-uid helper
  3. untar the backup into the data dir
  4. `docker start` the container

This is destructive — the existing volume is overwritten. Pass
`--yes` to confirm, or `--dry-run` to inspect the plan first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    container_exists,
    container_state,
    start_container,
    stop_container,
    wait_for_tcp,
)
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(
    profile: Profile,
    *,
    source: Path,
    yes: bool = False,
    dry_run: bool = False,
    wait_timeout: float = 90.0,
    timeout: float = 600.0,
) -> dict[str, Any]:
    src = Path(source)
    data_dir = str(profile.data_dir)

    steps = [
        f"# source={src}; data_dir={data_dir}",
        f"docker stop -t 60 {profile.container}",
        (f"docker run --rm --user 0 -v {data_dir}:/target "
         "alpine sh -c 'rm -rf /target/mgr /target/iris.cpf'  # wipe"),
        (f"docker run --rm --user 0 -v {src.parent}:/src:ro "
         f"-v {data_dir}:/target alpine tar xzf /src/{src.name} "
         "-C /target --strip-components=1"),
        f"docker start {profile.container}",
    ]

    if not src.exists():
        return error_envelope(
            "restore",
            code=ErrorCode.NOT_FOUND,
            message=f"backup source not found: {src}",
        )

    if dry_run:
        return success_envelope("restore", {
            "source": str(src),
            "data_dir": data_dir,
            "container": profile.container,
            "dry_run": True,
            "steps": steps,
        })

    if not yes:
        return error_envelope(
            "restore",
            code=ErrorCode.USAGE,
            message=(
                "restore is destructive (wipes the data dir). "
                "Pass --yes to confirm, or --dry-run to inspect."
            ),
            hint="this overwrites the current volume; back up first if unsure",
        )

    if not container_exists(profile.container):
        return error_envelope(
            "restore",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    # Stop if running
    was_running = container_state(profile.container)["running"]
    if was_running:
        try:
            stop_container(profile.container, timeout=60)
        except DockerError as e:
            return error_envelope(
                "restore", code=ErrorCode.DOCKER_ERROR,
                message=f"docker stop failed: {e}",
            )

    # Wipe via helper
    from irisctl.docker_api import _run as _docker_run  # noqa: PLC0415
    try:
        _docker_run([
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{data_dir}:/target",
            "alpine", "sh", "-c", "rm -rf /target/mgr /target/iris.cpf",
        ], timeout=120)
    except DockerError as e:
        return error_envelope(
            "restore", code=ErrorCode.DOCKER_ERROR,
            message=f"wipe failed: {e}",
        )

    # Untar via helper
    try:
        _docker_run([
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{src.parent}:/src:ro",
            "-v", f"{data_dir}:/target",
            "alpine", "tar", "xzf", f"/src/{src.name}",
            "-C", "/target", "--strip-components=1",
        ], timeout=timeout)
    except DockerError as e:
        return error_envelope(
            "restore", code=ErrorCode.DOCKER_ERROR,
            message=f"untar failed: {e}",
        )

    # Start
    try:
        start_container(profile.container)
    except DockerError as e:
        return error_envelope(
            "restore", code=ErrorCode.DOCKER_ERROR,
            message=f"data restored, but docker start failed: {e}",
        )

    listeners = wait_for_tcp(profile.host, [
        profile.superserver_port, profile.web_port,
        profile.rpc_port, profile.vistalink_port,
    ], timeout=wait_timeout)

    return success_envelope("restore", {
        "source": str(src),
        "data_dir": data_dir,
        "container": profile.container,
        "listeners": listeners,
    })
