"""`irisctl docs <KEY>` — open the InterSystems docs page for KEY."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from irisctl.config import Profile
from irisctl.output import ErrorCode, error_envelope, success_envelope

DOCS_BASE = "https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls"


def build_docs_url(key: str) -> str:
    return f"{DOCS_BASE}?KEY={key.strip()}"


def run(
    profile: Profile,
    *,
    key: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not key:
        return error_envelope(
            "docs",
            code=ErrorCode.USAGE,
            message="docs needs a KEY (e.g. ADOCK, GSA_using_instance)",
            hint="example: irisctl docs GCM_rest",
        )
    url = build_docs_url(key)
    if dry_run:
        return success_envelope("docs", {"key": key, "url": url, "dry_run": True})

    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener is None:
        return error_envelope(
            "docs",
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
            "docs",
            code=ErrorCode.INTERNAL,
            message=f"failed to launch browser: {e}",
        )
    return success_envelope("docs", {"key": key, "url": url, "opened": True})
