"""`irisctl shell` — interactive `iris session` proxy.

A pure pass-through to `docker exec -it <container> iris session IRIS
-U <namespace>`. The user's terminal connects directly. We do a license
sanity check first (1 LU consumed for as long as the shell stays open).

`run()` returns a JSON envelope when `dry_run=True` (for tests + the
`--dry-run` flag); otherwise it `os.execvp`s into docker exec, replacing
the irisctl process.
"""

from __future__ import annotations

import os
from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import container_exists
from irisctl.license import fetch_status
from irisctl.output import ErrorCode, error_envelope, success_envelope


def build_exec_argv(profile: Profile, *, namespace: str) -> list[str]:
    return [
        "docker", "exec", "-it", profile.container,
        "iris", "session", "IRIS", "-U", namespace,
    ]


def run(
    profile: Profile,
    *,
    namespace: str = "%SYS",
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "shell",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    # License sanity check (advisory — shell consumes 1 LU for its
    # whole lifetime, but we don't refuse unless the budget is at zero).
    license_snapshot: dict[str, Any] | None = None
    warnings: list[str] = []
    try:
        status = fetch_status(profile)
        license_snapshot = {
            "consumed": status.consumed,
            "available": status.available,
            "cap": status.cap,
        }
        if not force and status.available < 1:
            return error_envelope(
                "shell",
                code=ErrorCode.LICENSE_EXHAUSTED,
                message=(
                    f"no LUs free (consumed={status.consumed}, "
                    f"cap={status.cap}). Pass --force to attempt anyway."
                ),
                hint="irisctl license users  # see who's holding LUs",
            )
        if status.available < 2:
            warnings.append(
                f"only {status.available} LU free — your shell will use 1"
            )
    except Exception:  # noqa: BLE001
        warnings.append("could not read license metrics; proceeding anyway")

    argv = build_exec_argv(profile, namespace=namespace)

    if dry_run:
        return success_envelope("shell", {
            "namespace": namespace,
            "argv": argv,
            "license": license_snapshot,
        }, warnings=warnings)

    # Replace the irisctl process — the user's terminal is now talking
    # to docker exec directly. Returns only on failure.
    os.execvp(argv[0], argv)
    return error_envelope(
        "shell",
        code=ErrorCode.DOCKER_ERROR,
        message="execvp returned (this should not happen)",
    )
