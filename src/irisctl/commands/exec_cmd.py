"""`irisctl exec` — run ObjectScript via `iris session` heredoc.

Three input modes:
- positional `<script>` — single inline command
- `--stdin` — read script from stdin
- `--file PATH` — read script from a host-side file

Each call consumes 1 LU. License pre-check refuses near the cap unless
`--force` is given.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from irisctl.config import Profile
from irisctl.exec_session import ExecError, session_exec
from irisctl.license import fetch_and_precheck
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(
    profile: Profile,
    *,
    namespace: str = "%SYS",
    script: str | None = None,
    stdin_text: str | None = None,
    file: Path | None = None,
    force: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    payload = _resolve_payload(script=script, stdin_text=stdin_text, file=file)
    if payload is None:
        return error_envelope(
            "exec",
            code=ErrorCode.USAGE,
            message="exec needs a script: pass it inline, via --stdin, or --file PATH",
            hint="examples: irisctl exec 'W $ZV'  |  irisctl exec --file foo.m",
        )

    refusal = fetch_and_precheck("exec", profile, op_cost=1, force=force)
    if refusal is not None:
        return refusal

    try:
        out = session_exec(profile, namespace=namespace,
                           script=payload, timeout=timeout)
    except ExecError as e:
        return error_envelope(
            "exec",
            code=ErrorCode.IRIS_ERROR,
            message=str(e),
            hint="check the script; remember M wants tab indentation in dotted blocks",
        )

    return success_envelope("exec", {
        "namespace": namespace,
        "output": out,
    })


def _resolve_payload(
    *,
    script: str | None,
    stdin_text: str | None,
    file: Path | None,
) -> str | None:
    if script is not None:
        return script
    if stdin_text is not None:
        return stdin_text
    if file is not None:
        return Path(file).read_text(encoding="utf-8")
    return None
