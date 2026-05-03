"""`iris session` heredoc wrapper with HALT injection.

The single place in the codebase that touches `docker exec` to talk to
IRIS interactively. Two safety guarantees per docs/iris-cli-plan.md §6.4:

1. Always end with HALT — QUIT only exits the current stack frame and
   leaves the session running, hanging the docker exec.
2. Pipe the script via stdin (heredoc) so $VARS in user code are not
   shell-expanded.

Each call consumes 1 license unit on the IRIS side.
"""

from __future__ import annotations

import re
import subprocess
import time

from irisctl.config import Profile


class ExecError(Exception):
    """`iris session` invocation failed (non-zero exit, IRIS error, timeout)."""


_QUIT_RE = re.compile(r"^\s*(?:QUIT|Q)\b\s*$", re.IGNORECASE | re.MULTILINE)


def ensure_halt(script: str) -> str:
    """Make sure the script ends with HALT; replace trailing QUIT/Q.

    Trailing comments and whitespace are tolerated. If the last
    non-blank line is QUIT/Q, replace it with HALT. If the last
    non-blank line is `H` or HALT (case-insensitive), leave as-is.
    Otherwise append HALT.
    """
    lines = script.splitlines()
    # Find last non-empty line
    last_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last_idx = i
            break
    if last_idx < 0:
        return script + "\nHALT\n"

    last = lines[last_idx].strip().upper()
    if last in ("HALT", "H"):
        return script.rstrip() + "\n"
    if _QUIT_RE.match(lines[last_idx]):
        # Replace trailing QUIT/Q with HALT
        lines[last_idx] = "HALT"
        return "\n".join(lines) + "\n"
    return script.rstrip() + "\nHALT\n"


def session_exec(
    profile: Profile,
    *,
    namespace: str,
    script: str,
    timeout: float = 60.0,
    license_retry: bool = True,
) -> str:
    """Run `iris session IRIS -U <namespace>` with `script` on stdin.

    Returns stdout. Raises ExecError on non-zero exit, IRIS error
    output, or timeout.

    If `license_retry` is True (default) and the call fails with
    `<LICENSE LIMIT EXCEEDED>`, the wrapper sleeps briefly and retries
    once. The IRIS Community Edition LU counter can lag actual session
    state by ~1s, so a one-shot retry handles the common rapid-call case
    without exposing transient LU contention to callers.
    """
    cmd = [
        "docker", "exec", "-i", profile.container,
        "iris", "session", "IRIS", "-U", namespace,
    ]
    payload = ensure_halt(script)

    out, err, rc = _run_once(cmd, payload, timeout)

    if rc != 0 and "No such container" in err:
        raise ExecError(f"container {profile.container!r} not found")

    if license_retry and _is_license_exhausted(out, err):
        time.sleep(1.0)
        out, err, rc = _run_once(cmd, payload, timeout)

    if rc != 0:
        raise ExecError(
            f"iris session exit {rc}: "
            f"{(err.strip() or out.strip())[:400]}"
        )

    if _looks_like_iris_error(out):
        raise ExecError(f"IRIS error: {_extract_iris_error(out)}")
    return out


def _run_once(cmd: list[str], payload: str, timeout: float) -> tuple[str, str, int]:
    try:
        res = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ExecError(f"timeout after {timeout}s: {' '.join(cmd[:5])}") from e
    except FileNotFoundError as e:
        raise ExecError("docker CLI not found on PATH") from e
    return res.stdout or "", res.stderr or "", res.returncode


def _is_license_exhausted(out: str, err: str) -> bool:
    return ("LICENSE LIMIT EXCEEDED" in out
            or "LICENSE LIMIT EXCEEDED" in err)


def _looks_like_iris_error(out: str) -> bool:
    return bool(_IRIS_ERROR_RE.search(out))


def _extract_iris_error(out: str) -> str:
    m = _IRIS_ERROR_RE.search(out)
    return m.group(0).strip() if m else out.strip()[:400]


# IRIS error tokens look like <SYNTAX>, <UNDEFINED>, <NOROUTINE>, etc.
# %SYS-prompt errors usually print on their own line.
_IRIS_ERROR_RE = re.compile(
    r"<[A-Z][A-Z0-9_ ]*>(?:\^[A-Za-z0-9._%+]+)?(?:\s.*)?",
)
