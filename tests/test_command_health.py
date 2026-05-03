"""Tests for `irisctl health`."""

from __future__ import annotations

import pytest

from irisctl.commands.health import run as health_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestHealthLive:
    def test_returns_verdict(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = health_run(prof)
        # Health may be ok=False if anything is red; but the envelope shape
        # is fixed.
        d = env["data"] if env["ok"] else env["error"]
        assert "verdict" in d or env["error"]["code"]
        # When healthy, verdict is "green" or "yellow"
        if env["ok"]:
            assert env["data"]["verdict"] in ("green", "yellow")

    def test_lists_checks(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = health_run(prof)
        if env["ok"]:
            assert "checks" in env["data"]
            assert isinstance(env["data"]["checks"], list)
            # Each check has name + result
            for c in env["data"]["checks"]:
                assert "name" in c
                assert "ok" in c


class TestHealthError:
    def test_missing_container_yields_red(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = health_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"
