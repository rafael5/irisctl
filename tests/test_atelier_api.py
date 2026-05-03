"""Tests for the Atelier client.

The version probe runs without auth (it accepts 200 OR 401 as "endpoint
exists"). Auth-gated tests that need real credentials skip when none
are set in the environment.
"""

from __future__ import annotations

import os

import pytest

from irisctl.atelier_api import (
    AtelierClient,
    AuthRequired,
    probe_version,
)
from irisctl.http_api import NetworkError


def _have_creds() -> bool:
    return bool(os.environ.get("IRISCTL_AUTH_USER")
                and os.environ.get("IRISCTL_AUTH_PW"))


def _creds() -> tuple[str, str]:
    return (os.environ["IRISCTL_AUTH_USER"], os.environ["IRISCTL_AUTH_PW"])


@pytest.mark.integration
class TestProbeVersion:
    def test_probe_finds_a_version(self, live_iris):
        """Auth-free probe — accepts 200 or 401 as 'exists'."""
        v = probe_version(base_url="http://localhost:52773")
        assert v in ("v1", "v2", "v3", "v4", "v5", "v6")

    def test_probe_prefers_highest(self, live_iris):
        # On 2026.1, every version returns 401 (exists, auth-gated). The
        # probe should pick v6 (the newest).
        assert probe_version(base_url="http://localhost:52773") == "v6"

    def test_probe_unreachable_raises(self):
        with pytest.raises(NetworkError):
            probe_version(base_url="http://127.0.0.1:1", timeout=0.5)


@pytest.mark.integration
class TestAtelierClientUnauth:
    def test_get_server_without_auth_raises(self, live_iris):
        client = AtelierClient(base_url="http://localhost:52773")
        with pytest.raises(AuthRequired):
            client.get_server()

    def test_doc_names_without_auth_raises(self, live_iris):
        client = AtelierClient(base_url="http://localhost:52773")
        with pytest.raises(AuthRequired):
            client.get_doc_names("USER")


@pytest.mark.integration
@pytest.mark.skipif(not _have_creds(),
                    reason="IRISCTL_AUTH_USER / IRISCTL_AUTH_PW not set")
class TestAtelierClientAuth:
    def test_get_server(self, live_iris):
        client = AtelierClient(base_url="http://localhost:52773", auth=_creds())
        info = client.get_server()
        assert "namespaces" in info
        assert isinstance(info["namespaces"], list)
        # USER and %SYS always exist on a foia install
        names = {n.upper() for n in info["namespaces"]}
        assert "USER" in names
        assert "%SYS" in names

    def test_get_doc_names_user(self, live_iris):
        client = AtelierClient(base_url="http://localhost:52773", auth=_creds())
        names = client.get_doc_names("USER")
        assert isinstance(names, list)
        # USER may be empty on a fresh install but the call should succeed

    def test_doc_round_trip(self, live_iris, tmp_path):
        client = AtelierClient(base_url="http://localhost:52773", auth=_creds())
        doc = "irisctlTEST.mac"
        content = ['irisctlTEST', ' W "hello-from-test",!', ' Q']
        try:
            client.put_doc("USER", doc, content)
            got = client.get_doc("USER", doc)
            assert isinstance(got["content"], list)
            assert any("hello-from-test" in line for line in got["content"])
        finally:
            client.delete_doc("USER", doc)


# ----------------- Unit: payload shaping -----------------


class TestPutDocPayload:
    def test_lines_to_payload(self):
        from irisctl.atelier_api import lines_to_put_payload
        payload = lines_to_put_payload(["line1", "line2"])
        assert payload["enc"] is False
        assert payload["content"] == ["line1", "line2"]


class TestParseGetDoc:
    def test_extracts_content_array(self):
        from irisctl.atelier_api import parse_get_doc
        body = {
            "result": {
                "name": "x.mac",
                "content": ["L1", "L2"],
                "status": "OK",
            }
        }
        out = parse_get_doc(body)
        assert out["name"] == "x.mac"
        assert out["content"] == ["L1", "L2"]

    def test_handles_flat_shape(self):
        # Some IRIS versions return content at the top level.
        from irisctl.atelier_api import parse_get_doc
        body = {"name": "x.mac", "content": ["L1"]}
        out = parse_get_doc(body)
        assert out["name"] == "x.mac"
        assert out["content"] == ["L1"]
