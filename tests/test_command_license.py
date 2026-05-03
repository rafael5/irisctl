"""Tests for the `license` subcommand."""

from __future__ import annotations

import pytest

from irisctl.commands.license import run as license_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestLicenseLive:
    def test_returns_success_envelope(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = license_run(prof)
        assert env["ok"] is True
        assert env["command"] == "license"

    def test_data_has_expected_fields(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = license_run(prof)
        d = env["data"]
        for key in ("consumed", "available", "cap", "percent_used",
                    "days_remaining"):
            assert key in d, f"missing {key}"
        assert d["cap"] == d["consumed"] + d["available"]
        assert 0 <= d["percent_used"] <= 100
        assert d["consumed"] >= 0


class TestLicenseError:
    def test_unreachable_host_returns_network_error_envelope(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")  # closed port
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = license_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "network_error"
