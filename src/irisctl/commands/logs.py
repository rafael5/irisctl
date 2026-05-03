"""`irisctl logs` — tail messages.log via host helper.

Routes through a transient root-uid alpine container so the wrapper
doesn't need host root to read mode-700 / UID-51773 host volumes.
"""

from __future__ import annotations

from typing import Any

from irisctl.config import Profile
from irisctl.docker_api import DockerError, tail_log_via_helper
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile, *, tail: int = 200) -> dict[str, Any]:
    log_path = profile.messages_log_path()
    try:
        text = tail_log_via_helper(str(log_path), tail=tail)
    except DockerError as e:
        return error_envelope(
            "logs",
            code=ErrorCode.DOCKER_ERROR,
            message=str(e),
            hint=f"check {log_path} exists in the container's bind-mount",
        )
    lines = [ln for ln in text.splitlines() if ln]
    return success_envelope("logs", {
        "path": str(log_path),
        "tail": tail,
        "lines": lines,
    })
