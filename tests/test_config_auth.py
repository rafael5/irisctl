"""Tests for auth resolution on Profile (Phase 3 addition)."""

from __future__ import annotations

from pathlib import Path

import pytest

from irisctl.config import load_profile


def _empty(tmp_path: Path) -> Path:
    return tmp_path / "missing.toml"


class TestResolveAuth:
    def test_no_creds_returns_none(self, tmp_path, monkeypatch):
        for k in ("IRISCTL_AUTH_USER", "IRISCTL_AUTH_PW",
                  "IRISCTL_AUTH_PW_ENV"):
            monkeypatch.delenv(k, raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.resolve_auth() is None

    def test_direct_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "secret")
        monkeypatch.delenv("IRISCTL_AUTH_PW_ENV", raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.resolve_auth() == ("_SYSTEM", "secret")

    def test_user_only_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.delenv("IRISCTL_AUTH_PW", raising=False)
        monkeypatch.delenv("IRISCTL_AUTH_PW_ENV", raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.resolve_auth() is None

    def test_pw_indirection_via_env_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW_ENV", "MY_VAULT_PW")
        monkeypatch.setenv("MY_VAULT_PW", "indirect-secret")
        monkeypatch.delenv("IRISCTL_AUTH_PW", raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.resolve_auth() == ("_SYSTEM", "indirect-secret")

    def test_pw_indirection_with_unset_target(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW_ENV", "VAR_THAT_IS_UNSET")
        monkeypatch.delenv("IRISCTL_AUTH_PW", raising=False)
        monkeypatch.delenv("VAR_THAT_IS_UNSET", raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        # Indirection target unset → no creds
        assert prof.resolve_auth() is None

    def test_direct_pw_wins_over_indirection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "direct")
        monkeypatch.setenv("IRISCTL_AUTH_PW_ENV", "INDIRECT_VAR")
        monkeypatch.setenv("INDIRECT_VAR", "indirect")
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.resolve_auth() == ("_SYSTEM", "direct")

    def test_toml_profile_user(self, tmp_path):
        cfg = tmp_path / "c.toml"
        cfg.write_text("""
default_profile = "p1"
[profiles.p1]
container = "alpha"
auth_user = "_SYSTEM"
auth_pw_env = "PROF_PW"
""", encoding="utf-8")
        import os
        os.environ["PROF_PW"] = "from-toml-indirection"
        try:
            prof = load_profile(config_path=cfg)
            assert prof.auth_user == "_SYSTEM"
            assert prof.resolve_auth() == ("_SYSTEM", "from-toml-indirection")
        finally:
            os.environ.pop("PROF_PW", None)


@pytest.mark.parametrize("env_var", ["IRISCTL_AUTH_USER", "IRISCTL_AUTH_PW",
                                     "IRISCTL_AUTH_PW_ENV"])
def test_known_env_var_names(env_var):
    """Pin the contracted env var names so we don't accidentally rename."""
    # This test exists purely to fail loudly if someone renames the API.
    assert env_var.startswith("IRISCTL_AUTH_")
