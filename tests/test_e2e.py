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


@pytest.mark.integration
class TestEndToEndPhase2:
    def test_exec_inline(self, live_iris):
        env = _cli("exec", "--ns", "%SYS", 'W "irisctl-e2e-exec",!')
        assert env["ok"] is True
        assert "irisctl-e2e-exec" in env["data"]["output"]

    def test_exec_stdin(self, live_iris):
        # Pipe ObjectScript via stdin
        env_proc = subprocess.run(
            [sys.executable, "-m", "irisctl", "exec", "--ns", "%SYS", "--stdin"],
            input='W $NAMESPACE,!',
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=60,
        )
        assert env_proc.returncode == 0, env_proc.stderr
        env = json.loads(env_proc.stdout)
        assert env["ok"] is True
        assert "%SYS" in env["data"]["output"]

    def test_sql_inline(self, live_iris):
        env = _cli("sql", "--ns", "USER", "SELECT 1 AS one, 'hi' AS s")
        assert env["ok"] is True
        assert env["data"]["rowcount"] == 1
        assert {"one", "s"} <= {c.lower() for c in env["data"]["columns"]}

    def test_sql_invalid_returns_iris_error(self, live_iris):
        # exit code 7 (iris_error) per the contract
        proc = subprocess.run(
            [sys.executable, "-m", "irisctl", "sql", "--ns", "USER", "SELECT FROM X"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=60,
        )
        assert proc.returncode == 7
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"]["code"] == "iris_error"

    def test_shell_dry_run(self, live_iris):
        env = _cli("shell", "--ns", "%SYS", "--dry-run")
        assert env["ok"] is True
        assert env["data"]["argv"][0] == "docker"
        assert "iris" in env["data"]["argv"]
