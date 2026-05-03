"""`irisctl license` — current license-unit consumption snapshot.

Reads /api/monitor/metrics. No LU consumed (HTTP path).
"""

from __future__ import annotations

from typing import Any

from irisctl.config import Profile
from irisctl.http_api import IrisHttpClient, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope

REF = "docs/iris-cli-surface.md#10-gotchas"


def run(profile: Profile) -> dict[str, Any]:
    client = IrisHttpClient(base_url=profile.web_base_url())
    try:
        metrics = client.metrics(prefix="iris_license_")
    except NetworkError as e:
        return error_envelope(
            "license",
            code=ErrorCode.NETWORK_ERROR,
            message=str(e),
            hint=f"is the IRIS web port {profile.web_port} reachable?",
            ref=REF,
        )

    by_name = {m.name: m.value for m in metrics}
    consumed = int(by_name.get("iris_license_consumed", 0))
    available = int(by_name.get("iris_license_available", 0))
    pct = int(by_name.get("iris_license_percent_used", 0))
    days = int(by_name.get("iris_license_days_remaining", 0))
    cap = consumed + available

    return success_envelope("license", {
        "consumed": consumed,
        "available": available,
        "cap": cap,
        "percent_used": pct,
        "days_remaining": days,
    })
