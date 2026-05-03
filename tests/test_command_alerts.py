"""Tests for `irisctl alerts`."""

from __future__ import annotations

import pytest

from irisctl.commands.alerts import run as alerts_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestAlertsLive:
    def test_returns_envelope(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = alerts_run(prof)
        assert env["ok"] is True
        assert env["command"] == "alerts"
        # data is a list of alert records (possibly empty)
        assert isinstance(env["data"], (list, dict))


class TestAlertsError:
    def test_unreachable_returns_network_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = alerts_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "network_error"
