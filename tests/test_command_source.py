"""Tests for `irisctl source list/get/put/delete/compile`."""

from __future__ import annotations

import os
import uuid

import pytest

from irisctl.commands.source import (
    compile_,
    delete,
    get,
    list_docs,
    put,
)
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


def _have_creds() -> bool:
    return bool(os.environ.get("IRISCTL_AUTH_USER")
                and os.environ.get("IRISCTL_AUTH_PW"))


# ----------------- Unauth: contracts when creds absent -----------------


@pytest.mark.integration
class TestSourceUnauth:
    def test_list_returns_auth_required(self, live_iris, tmp_path,
                                          monkeypatch):
        for k in ("IRISCTL_AUTH_USER", "IRISCTL_AUTH_PW",
                  "IRISCTL_AUTH_PW_ENV"):
            monkeypatch.delenv(k, raising=False)
        prof = _profile(tmp_path)
        env = list_docs(prof, namespace="USER")
        assert env["ok"] is False
        assert env["error"]["code"] == "auth_required"

    def test_get_returns_auth_required(self, live_iris, tmp_path, monkeypatch):
        for k in ("IRISCTL_AUTH_USER", "IRISCTL_AUTH_PW",
                  "IRISCTL_AUTH_PW_ENV"):
            monkeypatch.delenv(k, raising=False)
        prof = _profile(tmp_path)
        env = get(prof, namespace="USER", doc="x.mac")
        assert env["error"]["code"] == "auth_required"


@pytest.mark.integration
class TestSourceBadCreds:
    def test_list_returns_auth_failed(self, live_iris, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "definitely-wrong-x12345")
        prof = _profile(tmp_path)
        env = list_docs(prof, namespace="USER")
        assert env["error"]["code"] == "auth_failed"


# ----------------- Live: full CRUD round-trip (auth required) ---------


@pytest.mark.integration
@pytest.mark.skipif(not _have_creds(),
                    reason="IRISCTL_AUTH_USER / IRISCTL_AUTH_PW not set")
class TestSourceCRUD:
    def test_list_user_namespace(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = list_docs(prof, namespace="USER")
        assert env["ok"] is True
        assert env["data"]["namespace"] == "USER"
        assert isinstance(env["data"]["docs"], list)

    def test_put_get_delete_round_trip(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        # Generate a unique routine name to avoid collisions
        suffix = uuid.uuid4().hex[:8].upper()
        doc = f"irisctlT{suffix}.mac"
        content = [
            f"irisctlT{suffix} ; round-trip test",
            ' W "irisctl-source-roundtrip",!',
            ' Q',
        ]

        try:
            # PUT
            put_env = put(prof, namespace="USER", doc=doc,
                          content_lines=content)
            assert put_env["ok"] is True

            # GET
            get_env = get(prof, namespace="USER", doc=doc)
            assert get_env["ok"] is True
            assert get_env["data"]["name"] == doc
            got_content = get_env["data"]["content"]
            assert any("irisctl-source-roundtrip" in line
                       for line in got_content)
        finally:
            # DELETE
            del_env = delete(prof, namespace="USER", doc=doc)
            assert del_env["ok"] is True

    def test_get_nonexistent_returns_not_found(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = get(prof, namespace="USER", doc="irisctlNoSuch.mac")
        assert env["ok"] is False
        # Atelier returns 500 for non-existent docs in some builds; accept
        # either not_found or iris_error so the test doesn't assume too much.
        assert env["error"]["code"] in ("not_found", "iris_error")

    def test_compile_after_put(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        suffix = uuid.uuid4().hex[:8].upper()
        doc = f"irisctlC{suffix}.mac"
        content = [
            f"irisctlC{suffix} ; compile test",
            ' W "compile-ok",!',
            ' Q',
        ]
        try:
            put(prof, namespace="USER", doc=doc, content_lines=content)
            env = compile_(prof, namespace="USER", doc_names=[doc])
            assert env["ok"] is True
            assert env["data"]["compiled"] >= 1
        finally:
            delete(prof, namespace="USER", doc=doc)


# ----------------- Network errors -----------------


class TestSourceNetwork:
    def test_unreachable_returns_network_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")
        monkeypatch.setenv("IRISCTL_AUTH_USER", "_SYSTEM")
        monkeypatch.setenv("IRISCTL_AUTH_PW", "anything")
        prof = _profile(tmp_path)
        env = list_docs(prof, namespace="USER")
        assert env["error"]["code"] == "network_error"
