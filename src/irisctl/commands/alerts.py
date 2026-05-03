"""`irisctl alerts` — /api/monitor/alerts."""

from __future__ import annotations

from typing import Any

from irisctl.config import Profile
from irisctl.http_api import IrisHttpClient, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope

REF = "docs/iris-cli-surface.md#61-apimonitor--observability"


def run(profile: Profile) -> dict[str, Any]:
    client = IrisHttpClient(base_url=profile.web_base_url())
    try:
        data = client.alerts()
    except NetworkError as e:
        return error_envelope(
            "alerts",
            code=ErrorCode.NETWORK_ERROR,
            message=str(e),
            hint=f"is the IRIS web port {profile.web_port} reachable?",
            ref=REF,
        )
    return success_envelope("alerts", data)
