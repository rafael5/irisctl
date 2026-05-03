"""`irisctl config show` and `irisctl config merge`.

Show reads `iris.cpf` from the host bind-mount via a transient
root-uid helper container — no docker exec, no LU consumed.

Merge is the *only* safe path to mutate the live CPF (per the surface
doc: hand-edits to a running iris.cpf can be overwritten on shutdown).
It stages the user's fragment via `docker cp`, then runs
`iris merge IRIS /tmp/<staged>` inside the container.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import (
    DockerError,
    cat_file_via_helper,
    container_exists,
    cp_to_container,
    docker_exec,
)
from irisctl.output import ErrorCode, error_envelope, success_envelope

# ----------------- show -----------------


def show_run(profile: Profile) -> dict[str, Any]:
    cpf_path = str(profile.data_dir / "iris.cpf")
    try:
        text = cat_file_via_helper(cpf_path)
    except DockerError as e:
        return error_envelope(
            "config",
            code=ErrorCode.DOCKER_ERROR,
            message=str(e),
            hint=f"check that {cpf_path} exists on the host bind mount",
        )
    return success_envelope("config", {
        "path": cpf_path,
        "size_bytes": len(text.encode("utf-8")),
        "text": text,
    })


# ----------------- merge -----------------


def merge_run(
    profile: Profile,
    *,
    file: Path,
    dry_run: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    src = Path(file)
    if not src.exists() or not src.is_file():
        return error_envelope(
            "config",
            code=ErrorCode.USAGE,
            message=f"merge file not found: {src}",
            hint="pass an existing CPF fragment as the merge source",
        )

    staged = "/tmp/irisctl-merge.cpf"
    steps = [
        f"docker cp {src} {profile.container}:{staged}",
        f"docker exec {profile.container} iris merge IRIS {staged}",
    ]

    if dry_run:
        return success_envelope("config", {
            "source_file": str(src),
            "staged_path": staged,
            "container": profile.container,
            "dry_run": True,
            "steps": steps,
        })

    if not container_exists(profile.container):
        return error_envelope(
            "config",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    try:
        cp_to_container(str(src), profile.container, staged)
    except DockerError as e:
        return error_envelope(
            "config", code=ErrorCode.DOCKER_ERROR,
            message=f"docker cp failed: {e}",
        )

    try:
        out = docker_exec(
            profile.container,
            ["iris", "merge", "IRIS", staged],
            timeout=timeout,
        )
    except DockerError as e:
        return error_envelope(
            "config", code=ErrorCode.IRIS_ERROR,
            message=f"iris merge failed: {e}",
            hint="check the CPF fragment for syntax errors",
        )

    return success_envelope("config", {
        "source_file": str(src),
        "staged_path": staged,
        "container": profile.container,
        "iris_merge_output": out.strip(),
    })


# ----------------- dispatch -----------------


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "config_sub", None)
    if sub == "show":
        return show_run(profile)
    if sub == "merge":
        return merge_run(
            profile,
            file=Path(args.file),
            dry_run=getattr(args, "dry_run", False),
        )
    return error_envelope(
        "config",
        code=ErrorCode.USAGE,
        message="config needs a sub-verb: show | merge",
        hint="example: irisctl config show",
    )
