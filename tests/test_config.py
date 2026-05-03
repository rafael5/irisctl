"""Tests for the config / profile module."""

from __future__ import annotations

from pathlib import Path

import pytest

from irisctl.config import Profile, load_profile


def _write_toml(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8")
    return p


class TestDefaults:
    def test_defaults_when_no_config_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("IRISCTL_PROFILE", raising=False)
        monkeypatch.delenv("IRISCTL_CONTAINER", raising=False)
        monkeypatch.delenv("IRISCTL_HOST", raising=False)
        monkeypatch.delenv("IRISCTL_WEB_PORT", raising=False)
        prof = load_profile(config_path=tmp_path / "missing.toml")
        # Plan §5: default profile points at foia
        assert prof.container == "foia"
        assert prof.host == "127.0.0.1"
        assert prof.web_port == 52773
        assert prof.superserver_port == 1972

    def test_data_dir_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("IRISCTL_PROFILE", raising=False)
        prof = load_profile(config_path=tmp_path / "missing.toml")
        assert "foia-iris" in str(prof.data_dir)


class TestEnvOverrides:
    def test_env_overrides_container(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "myiris")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        assert prof.container == "myiris"

    def test_env_overrides_web_port(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_WEB_PORT", "12345")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        assert prof.web_port == 12345

    def test_env_overrides_host(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "192.168.1.50")
        prof = load_profile(config_path=tmp_path / "missing.toml")
        assert prof.host == "192.168.1.50"


class TestTomlProfile:
    def test_picks_default_profile(self, tmp_path, monkeypatch):
        monkeypatch.delenv("IRISCTL_PROFILE", raising=False)
        cfg = _write_toml(tmp_path / "c.toml", """
default_profile = "p1"
[profiles.p1]
container = "alpha"
host = "10.0.0.1"
web_port = 9000
superserver_port = 1972
""")
        prof = load_profile(config_path=cfg)
        assert prof.container == "alpha"
        assert prof.host == "10.0.0.1"
        assert prof.web_port == 9000

    def test_named_profile_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_PROFILE", "p2")
        cfg = _write_toml(tmp_path / "c.toml", """
default_profile = "p1"
[profiles.p1]
container = "alpha"
host = "10.0.0.1"
[profiles.p2]
container = "beta"
host = "10.0.0.2"
""")
        prof = load_profile(config_path=cfg)
        assert prof.container == "beta"

    def test_explicit_profile_argument_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_PROFILE", "ignored")
        cfg = _write_toml(tmp_path / "c.toml", """
default_profile = "p1"
[profiles.p1]
container = "alpha"
[profiles.named]
container = "winner"
""")
        prof = load_profile(profile="named", config_path=cfg)
        assert prof.container == "winner"

    def test_unknown_profile_raises(self, tmp_path):
        cfg = _write_toml(tmp_path / "c.toml", """
default_profile = "p1"
[profiles.p1]
container = "alpha"
""")
        with pytest.raises(KeyError):
            load_profile(profile="missing", config_path=cfg)


class TestUrl:
    def test_metrics_base_url(self):
        prof = Profile(container="x", host="localhost", web_port=52773,
                       superserver_port=1972, data_dir=Path("/tmp"))
        assert prof.web_base_url() == "http://localhost:52773"

    def test_handles_explicit_scheme(self):
        prof = Profile(container="x", host="localhost", web_port=8080,
                       superserver_port=1972, data_dir=Path("/tmp"))
        assert prof.web_base_url() == "http://localhost:8080"
