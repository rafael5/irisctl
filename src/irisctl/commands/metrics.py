"""`irisctl metrics` — Prometheus counters from /api/monitor/metrics.

Sub-verbs:
- (default) — list filtered metrics as records
- describe NAME — single counter detail
- scrape — raw Prometheus text in `data.raw`
"""

from __future__ import annotations

import argparse
from typing import Any

from irisctl.config import Profile
from irisctl.http_api import IrisHttpClient, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope

REF = "docs/iris-cli-surface.md#7-live-metrics-inventory"


def _client(profile: Profile) -> IrisHttpClient:
    return IrisHttpClient(base_url=profile.web_base_url())


def list_metrics(profile: Profile, *, prefix: str | None) -> dict[str, Any]:
    try:
        metrics = _client(profile).metrics(prefix=prefix)
    except NetworkError as e:
        return _network_error(e, profile)
    return success_envelope(
        "metrics", [m.to_dict() for m in metrics]
    )


def describe(profile: Profile, name: str) -> dict[str, Any]:
    try:
        metrics = _client(profile).metrics(prefix=name)
    except NetworkError as e:
        return _network_error(e, profile)
    matching = [m for m in metrics if m.name == name]
    if not matching:
        return error_envelope(
            "metrics",
            code=ErrorCode.NOT_FOUND,
            message=f"metric {name!r} not found",
            hint="run `irisctl metrics --prefix iris_` to enumerate",
            ref=REF,
        )
    if len(matching) == 1:
        return success_envelope("metrics", matching[0].to_dict())
    # Multi-sample (different label sets) — return all of them.
    return success_envelope(
        "metrics",
        {"name": name, "samples": [m.to_dict() for m in matching]},
    )


def scrape(profile: Profile) -> dict[str, Any]:
    try:
        text = _client(profile).metrics_raw()
    except NetworkError as e:
        return _network_error(e, profile)
    return success_envelope("metrics", {"raw": text})


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "metrics_sub", None)
    if sub == "describe":
        return describe(profile, args.name)
    if sub == "scrape":
        return scrape(profile)
    return list_metrics(profile, prefix=getattr(args, "prefix", None))


def _network_error(e: Exception, profile: Profile) -> dict[str, Any]:
    return error_envelope(
        "metrics",
        code=ErrorCode.NETWORK_ERROR,
        message=str(e),
        hint=f"is the IRIS web port {profile.web_port} reachable?",
        ref=REF,
    )
