"""Tests for `irisctl version`."""

from __future__ import annotations

import pytest

from irisctl.commands.version import run as version_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestVersionLive:
    def test_returns_envelope_with_image_labels(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = version_run(prof)
        assert env["ok"] is True
        d = env["data"]
        assert "image_version" in d
        assert "platform_version" in d
        assert "instance" in d
        # Expected values for the foia image in this repo
        assert d["instance"] == "IRIS"
        assert d["platform_version"].startswith("2026")

    def test_includes_irisctl_version(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = version_run(prof)
        assert env["data"]["irisctl_version"] == "0.1.0"


class TestVersionError:
    def test_missing_container_returns_instance_not_running(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = version_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"
