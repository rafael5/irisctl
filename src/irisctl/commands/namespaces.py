"""`irisctl namespaces` — list namespaces via Atelier GetServer."""

from __future__ import annotations

from typing import Any

from irisctl.atelier_api import AtelierClient
from irisctl.config import Profile
from irisctl.http_api import AuthRequired, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile) -> dict[str, Any]:
    auth = profile.resolve_auth()
    if auth is None:
        return error_envelope(
            "namespaces",
            code=ErrorCode.AUTH_REQUIRED,
            message="atelier endpoint requires credentials",
            hint=("set IRISCTL_AUTH_USER and IRISCTL_AUTH_PW "
                  "(or IRISCTL_AUTH_PW_ENV)"),
        )

    client = AtelierClient(base_url=profile.web_base_url(), auth=auth)
    try:
        info = client.get_server()
    except AuthRequired:
        return error_envelope(
            "namespaces",
            code=ErrorCode.AUTH_FAILED,
            message="credentials rejected by IRIS (HTTP 401)",
            hint="check IRISCTL_AUTH_USER / IRISCTL_AUTH_PW values",
        )
    except NetworkError as e:
        return error_envelope(
            "namespaces",
            code=ErrorCode.NETWORK_ERROR,
            message=str(e),
            hint=f"is the IRIS web port {profile.web_port} reachable?",
        )

    return success_envelope("namespaces", {
        "atelier_version": client.version,
        "server": info.get("version", ""),
        "instance": info.get("name", ""),
        "namespaces": info.get("namespaces", []),
    })
