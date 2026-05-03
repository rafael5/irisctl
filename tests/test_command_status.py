"""Tests for `irisctl status`."""

from __future__ import annotations

import pytest

from irisctl.commands.status import run as status_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestStatusLive:
    def test_returns_composite_snapshot(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = status_run(prof)
        assert env["ok"] is True
        d = env["data"]
        for key in ("container", "listeners", "license", "system_state"):
            assert key in d, f"missing {key}"

    def test_container_block(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = status_run(prof)
        c = env["data"]["container"]
        assert c["running"] is True
        assert c["status"] == "running"

    def test_listeners_block(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = status_run(prof)
        ls = env["data"]["listeners"]
        # Each listener has reachable=True/False
        roles = {row["role"] for row in ls}
        assert "web" in roles
        assert "superserver" in roles

    def test_license_block(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = status_run(prof)
        lic = env["data"]["license"]
        assert "consumed" in lic
        assert "available" in lic


class TestStatusError:
    def test_missing_container(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = status_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"
