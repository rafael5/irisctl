"""`irisctl backup` — tar the host volume to a backup tarball.

Sequence (per INSTALL_GUIDE.md §8 "Backups"):
  1. `docker stop` the container so journals flush
  2. tar the data dir via a root-uid helper
  3. `docker start` the container

If `online=True` (default), the stop/start is skipped — the tar runs
against the live volume while IRIS keeps writing. This is faster but
the snapshot may be inconsistent across the journal boundary; suitable
for casual snapshots, not disaster recovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    container_exists,
    container_state,
    start_container,
    stop_container,
)
from irisctl.output import ErrorCode, error_envelope, success_envelope


def _default_path() -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "data" / "backups" / f"foia-iris-{ts}.tgz"


def run(
    profile: Profile,
    *,
    to: Path | None = None,
    online: bool = True,
    dry_run: bool = False,
    timeout: float = 600.0,
) -> dict[str, Any]:
    out = Path(to) if to is not None else _default_path()
    out.parent.mkdir(parents=True, exist_ok=True)

    data_dir = str(profile.data_dir)
    steps = [
        f"# online={online}; out={out}",
        ("# (skipping stop — online backup)"
         if online else
         f"docker stop -t 60 {profile.container}"),
        (f"docker run --rm --user 0 -v {data_dir}:/data:ro -v {out.parent}:/out "
         f"alpine tar czf /out/{out.name} -C / data"),
        ("# (skipping start — was online)"
         if online else
         f"docker start {profile.container}"),
    ]

    if dry_run:
        return success_envelope("backup", {
            "path": str(out),
            "online": online,
            "dry_run": True,
            "steps": steps,
        })

    if not container_exists(profile.container):
        return error_envelope(
            "backup",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    was_running = container_state(profile.container)["running"]

    if not online and was_running:
        try:
            stop_container(profile.container, timeout=60)
        except DockerError as e:
            return error_envelope(
                "backup", code=ErrorCode.DOCKER_ERROR,
                message=f"docker stop failed: {e}",
            )

    # tar via helper container
    try:
        from irisctl.docker_api import _run as _docker_run  # noqa: PLC0415
        _docker_run([
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{data_dir}:/data:ro",
            "-v", f"{out.parent}:/out",
            "alpine", "tar", "czf", f"/out/{out.name}", "-C", "/", "data",
        ], timeout=timeout)
    except DockerError as e:
        # Try to restart container before bailing if we stopped it
        if not online and was_running:
            try:
                start_container(profile.container)
            except DockerError:
                pass
        return error_envelope(
            "backup", code=ErrorCode.DOCKER_ERROR,
            message=f"tar failed: {e}",
        )

    if not online and was_running:
        try:
            start_container(profile.container)
        except DockerError as e:
            return error_envelope(
                "backup", code=ErrorCode.DOCKER_ERROR,
                message=f"backup tarball ok, but docker start failed: {e}",
            )

    size = out.stat().st_size if out.exists() else 0
    return success_envelope("backup", {
        "path": str(out),
        "size_bytes": size,
        "online": online,
        "container_was_running": was_running,
    })
