"""Helper for not-yet-implemented commands (Phase 1 stubs)."""

from typing import Any

from irisctl.output import ErrorCode, error_envelope


def not_implemented(command: str) -> dict[str, Any]:
    return error_envelope(
        command,
        code=ErrorCode.INTERNAL,
        message=f"{command}: not implemented yet",
        hint="check `irisctl --help` for what's wired up",
    )
