"""End-to-end CLI tests — every Phase 1 subcommand via subprocess.

These verify the full chain: argparse → dispatch → command function →
real foia container → output envelope. Each command is invoked just
like a user would invoke it from the shell.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _cli(*args: str, expect_returncode: int = 0) -> dict:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    res = subprocess.run(
        [sys.executable, "-m", "irisctl", *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == expect_returncode, (
        f"rc={res.returncode}, expected {expect_returncode}\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
    return json.loads(res.stdout)


@pytest.mark.integration
class TestEndToEnd:
    def test_license(self, live_iris):
        env = _cli("license")
        assert env["ok"] is True
        assert env["command"] == "license"
        assert env["data"]["cap"] == 8

    def test_metrics_default(self, live_iris):
        env = _cli("metrics", "--prefix", "iris_license_")
        assert env["ok"] is True
        assert all(m["name"].startswith("iris_license_") for m in env["data"])

    def test_metrics_describe(self, live_iris):
        env = _cli("metrics", "describe", "iris_license_consumed")
        assert env["ok"] is True
        assert env["data"]["name"] == "iris_license_consumed"

    def test_metrics_scrape(self, live_iris):
        env = _cli("metrics", "scrape")
        assert env["ok"] is True
        assert "# HELP" in env["data"]["raw"]

    def test_alerts(self, live_iris):
        env = _cli("alerts")
        assert env["ok"] is True
        assert env["command"] == "alerts"

    def test_version(self, live_iris):
        env = _cli("version")
        assert env["ok"] is True
        assert env["data"]["instance"] == "IRIS"
        assert env["data"]["irisctl_version"] == "0.1.0"

    def test_ports(self, live_iris):
        env = _cli("ports")
        assert env["ok"] is True
        host_ports = {r["host_port"] for r in env["data"]}
        assert {1972, 52773, 9430, 8001} <= host_ports

    def test_logs(self, live_iris):
        env = _cli("logs", "--tail", "10")
        assert env["ok"] is True
        assert env["data"]["path"].endswith("messages.log")

    def test_status(self, live_iris):
        env = _cli("status")
        assert env["ok"] is True
        assert env["data"]["container"]["running"] is True

    def test_health(self, live_iris):
        env = _cli("health")
        assert env["ok"] is True
        assert env["data"]["verdict"] in ("green", "yellow")
