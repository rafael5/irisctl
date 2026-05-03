"""`irisctl portal [PATH]` — open the Mgmt Portal in the default browser.

Builds a URL from the active profile + optional CSP path, then either
dry-runs (returning the URL in the envelope) or shells out to
`xdg-open`. Default path lands on the portal home.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from irisctl.config import Profile
from irisctl.output import ErrorCode, error_envelope, success_envelope


def build_portal_url(profile: Profile, *, path: str | None) -> str:
    base = f"http://{profile.host}:{profile.web_port}"
    if path is None:
        return f"{base}/csp/sys/UtilHome.csp"
    p = path.lstrip("/")
    if p.startswith("csp/"):
        return f"{base}/{p}"
    return f"{base}/csp/sys/{p}"


def run(
    profile: Profile,
    *,
    path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    url = build_portal_url(profile, path=path)
    if dry_run:
        return success_envelope("portal", {"url": url, "dry_run": True})

    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener is None:
        return error_envelope(
            "portal",
            code=ErrorCode.INTERNAL,
            message="no browser opener (xdg-open / open) found on PATH",
            hint=f"open this URL manually: {url}",
        )
    try:
        subprocess.Popen([opener, url],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as e:
        return error_envelope(
            "portal",
            code=ErrorCode.INTERNAL,
            message=f"failed to launch browser: {e}",
        )
    return success_envelope("portal", {"url": url, "opened": True})
