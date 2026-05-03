"""License pre-check helper for LU-consuming subcommands.

Phase 2's `exec`, `sql`, and `shell` each consume one license unit per
invocation. This helper reads /api/monitor/metrics, classifies whether
the call would be safe, and returns either None (proceed) or an error
envelope (refuse).

Distinct from `commands/license.py` (the user-facing snapshot command).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from irisctl.config import Profile
from irisctl.http_api import IrisHttpClient, NetworkError
from irisctl.output import ErrorCode, error_envelope

REF = "docs/iris-cli-surface.md#10-gotchas"


@dataclass
class LicenseStatus:
    consumed: int
    available: int
    cap: int
    percent_used: int
    days_remaining: int


def fetch_status(profile: Profile) -> LicenseStatus:
    """Read the live license counters from /api/monitor/metrics."""
    client = IrisHttpClient(base_url=profile.web_base_url())
    metrics = client.metrics(prefix="iris_license_")
    by_name = {m.name: m.value for m in metrics}
    consumed = int(by_name.get("iris_license_consumed", 0))
    available = int(by_name.get("iris_license_available", 0))
    return LicenseStatus(
        consumed=consumed,
        available=available,
        cap=consumed + available,
        percent_used=int(by_name.get("iris_license_percent_used", 0)),
        days_remaining=int(by_name.get("iris_license_days_remaining", 0)),
    )


def precheck(
    command: str,
    status: LicenseStatus,
    *,
    op_cost: int = 1,
    reserve: int = 1,
    force: bool = False,
) -> dict[str, Any] | None:
    """Return None if the operation can proceed; an error envelope if not."""
    if force:
        return None
    if status.available - op_cost < reserve:
        return error_envelope(
            command,
            code=ErrorCode.LICENSE_EXHAUSTED,
            message=(
                f"need {op_cost} LU; only {status.available} free "
                f"(consumed={status.consumed}, cap={status.cap}, "
                f"reserve={reserve}). Pass --force to bypass."
            ),
            hint="irisctl license   # see current consumption",
            ref=REF,
        )
    return None


def fetch_and_precheck(
    command: str,
    profile: Profile,
    *,
    op_cost: int = 1,
    reserve: int = 1,
    force: bool = False,
) -> dict[str, Any] | None:
    """Convenience: fetch status + precheck. Returns None or error envelope."""
    try:
        status = fetch_status(profile)
    except NetworkError as e:
        return error_envelope(
            command,
            code=ErrorCode.NETWORK_ERROR,
            message=f"could not read license metrics: {e}",
            hint=f"is the IRIS web port {profile.web_port} reachable?",
            ref=REF,
        )
    return precheck(command, status, op_cost=op_cost, reserve=reserve, force=force)
