"""Tests for `irisctl ports`."""

from __future__ import annotations

import pytest

from irisctl.commands.ports import run as ports_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestPortsLive:
    def test_returns_listener_table(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = ports_run(prof)
        assert env["ok"] is True
        rows = env["data"]
        assert isinstance(rows, list)
        # One row per IRIS listener
        roles = {r["role"] for r in rows}
        assert "superserver" in roles
        assert "web" in roles
        assert "rpc_broker" in roles
        assert "vistalink" in roles

    def test_well_known_ports_open(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = ports_run(prof)
        rows = env["data"]
        web_row = next(r for r in rows if r["role"] == "web")
        assert web_row["host_port"] == 52773
        assert web_row["reachable"] is True

    def test_each_row_has_required_fields(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = ports_run(prof)
        for r in env["data"]:
            assert {"role", "container_port", "host_port", "reachable"} <= set(r)


class TestPortsError:
    def test_missing_container_returns_instance_not_running(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = ports_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"
