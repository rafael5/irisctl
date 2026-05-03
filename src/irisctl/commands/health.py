"""`irisctl health` — composite "should I worry" verdict.

Aggregates checks across container state, listener reachability, alert
log, and system state. Returns a green/yellow verdict on success or a
structured error if a hard prerequisite is missing.
"""

from __future__ import annotations

from typing import Any

from irisctl.commands import alerts as cmd_alerts
from irisctl.commands import ports as cmd_ports
from irisctl.commands import status as cmd_status
from irisctl.config import Profile
from irisctl.output import success_envelope


def run(profile: Profile) -> dict[str, Any]:
    status_env = cmd_status.run(profile)
    if not status_env["ok"]:
        # Hard prerequisite missing — propagate the envelope as-is but
        # rename the command field for clarity.
        return {**status_env, "command": "health"}

    ports_env = cmd_ports.run(profile)
    alerts_env = cmd_alerts.run(profile)

    checks: list[dict[str, Any]] = [
        _check("container_running",
               status_env["data"]["container"]["running"]),
        _check("listeners_all_reachable",
               ports_env["ok"]
               and all(r.get("reachable") for r in ports_env["data"])),
        _check("alerts_endpoint_reachable", alerts_env["ok"]),
    ]

    license_data = status_env["data"].get("license") or {}
    if license_data:
        # License headroom: yellow if <2 LUs free, green otherwise.
        avail = int(license_data.get("available", 0))
        checks.append(_check(
            "license_headroom",
            avail >= 2,
            note=f"{avail} LUs free of {license_data.get('cap')}",
        ))

    if alerts_env["ok"] and isinstance(alerts_env["data"], list):
        checks.append(_check(
            "no_new_alerts",
            len(alerts_env["data"]) == 0,
            note=f"{len(alerts_env['data'])} alert(s) since last scrape",
        ))

    failures = [c for c in checks if not c["ok"]]
    verdict = "green" if not failures else "yellow"

    return success_envelope("health", {
        "verdict": verdict,
        "checks": checks,
        "failures": [c["name"] for c in failures],
    })


def _check(name: str, ok: bool, *, note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "ok": bool(ok)}
    if note is not None:
        out["note"] = note
    return out
