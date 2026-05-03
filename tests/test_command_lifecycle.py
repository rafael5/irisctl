"""Tests for `irisctl start/stop/restart/recreate`.

Cheap paths (idempotent no-ops, validation, dry-run) run as normal
integration tests. Full container cycles (real stop+start) are gated
behind `@pytest.mark.slow` and run only via `make test-slow`.
"""

from __future__ import annotations

import pytest

from irisctl.commands.lifecycle import (
    recreate_run,
    restart_run,
    start_run,
    stop_run,
)
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- Cheap paths -----------------


@pytest.mark.integration
class TestStartIdempotent:
    def test_already_running_is_noop(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = start_run(prof)
        assert env["ok"] is True
        assert env["data"]["already_running"] is True


@pytest.mark.integration
class TestStartMissing:
    def test_missing_container_returns_instance_not_running(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        env = start_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"


@pytest.mark.integration
class TestStopMissing:
    def test_missing_container_returns_instance_not_running(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        env = stop_run(prof, timeout=1)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"


class TestRecreateGuards:
    def test_refuses_without_yes(self, tmp_path):
        prof = _profile(tmp_path)
        env = recreate_run(prof, image="foia:latest", yes=False)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
        assert "--yes" in env["error"]["message"]

    def test_dry_run_returns_argv_without_yes(self, tmp_path):
        prof = _profile(tmp_path)
        env = recreate_run(prof, image="foia:latest",
                           yes=False, dry_run=True)
        # dry_run skips the safety check and returns the would-be argv
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        assert "argv" in env["data"]


# ----------------- Slow: full lifecycle cycle ---------


@pytest.mark.integration
@pytest.mark.slow
class TestStopThenStart:
    """Full stop+start cycle (~60-90s) — opt in via `make test-slow`."""

    def test_stop_then_start(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        # Stop with a generous timeout
        stop_env = stop_run(prof, timeout=60)
        assert stop_env["ok"] is True
        assert stop_env["data"]["was_running"] is True

        # Start back up — wait for listeners
        start_env = start_run(prof, wait_timeout=90)
        assert start_env["ok"] is True
        assert start_env["data"]["already_running"] is False
        # All four listeners should be reachable after start
        listeners = start_env["data"]["listeners"]
        for port in (1972, 52773, 9430, 8001):
            assert listeners.get(port) is True, f"port {port} not reachable"


@pytest.mark.integration
@pytest.mark.slow
class TestRestart:
    def test_restart_full_cycle(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = restart_run(prof, timeout=60, wait_timeout=90)
        assert env["ok"] is True
        listeners = env["data"]["listeners"]
        for port in (1972, 52773, 9430, 8001):
            assert listeners.get(port) is True, f"port {port} not reachable"
