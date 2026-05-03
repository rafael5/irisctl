"""Tests for `irisctl namespaces`."""

from __future__ import annotations

import os

import pytest

from irisctl.commands.namespaces import run as namespaces_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


def _have_creds() -> bool:
    return bool(os.environ.get("IRISCTL_AUTH_USER")
                and os.environ.get("IRISCTL_AUTH_PW"))


@pytest.mark.integration
class TestNamespacesUnauth:
    def test_no_creds_returns_auth_required(self, live_iris, tmp_path,
                                            monkeypatch):
        for k in ("IRISCTL_AUTH_USER", "IRISCTL_AUTH_PW",
                  "IRISCTL_AUTH_PW_ENV"):
            monkeypatch.delenv(k, raising=False)
        prof = _profile(tmp_path)
        env = namespaces_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "auth_required"
        assert "IRISCTL_AUTH" in env["error"]["hint"]

    def test_bad_creds_returns_auth_failed(self, live_iris, tmp_path,
                                            monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "definitely-wrong-password")
        prof = _profile(tmp_path)
        env = namespaces_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "auth_failed"


@pytest.mark.integration
@pytest.mark.skipif(not _have_creds(),
                    reason="IRISCTL_AUTH_USER / IRISCTL_AUTH_PW not set")
class TestNamespacesAuth:
    def test_returns_namespace_list(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = namespaces_run(prof)
        assert env["ok"] is True
        d = env["data"]
        assert "namespaces" in d
        names = {n.upper() for n in d["namespaces"]}
        assert "USER" in names
        assert "%SYS" in names


class TestNamespacesError:
    def test_unreachable_returns_network_error(self, tmp_path, monkeypatch):
        # Auth must be set so we get past the auth precheck and hit the network
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "anything")
        prof = _profile(tmp_path)
        env = namespaces_run(prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "network_error"
