"""Tests for the JSON-RPC server loop.

Single-persistent-process mode for AI agents — sends JSON-RPC 2.0
requests on stdin, gets envelopes back on stdout. Avoids spawning
~28 distinct CLI processes for the same operations.
"""

from __future__ import annotations

import io
import json

import pytest

from irisctl.config import load_profile
from irisctl.rpc import (
    METHODS,
    handle_request,
    serve,
)


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- handle_request (unit) -----------------


class TestHandleRequest:
    def test_unknown_method(self, tmp_path):
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "not_a_method", "id": 1}
        resp = handle_request(req, prof)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "error" in resp
        # JSON-RPC method-not-found error code
        assert resp["error"]["code"] == -32601

    def test_missing_jsonrpc_field(self, tmp_path):
        prof = _profile(tmp_path)
        req = {"method": "which", "id": 1}
        resp = handle_request(req, prof)
        # We accept either jsonrpc=2.0 missing or relaxed mode — should
        # still respond, but with -32600 invalid request
        assert "error" in resp
        assert resp["error"]["code"] == -32600

    def test_which_method(self, tmp_path):
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "which",
               "params": {"op": "license"}, "id": 7}
        resp = handle_request(req, prof)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 7
        assert "result" in resp
        # The result is the irisctl envelope
        env = resp["result"]
        assert env["ok"] is True
        assert env["data"]["op"] == "license"

    def test_which_no_params(self, tmp_path):
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "which", "id": 1}
        resp = handle_request(req, prof)
        assert "result" in resp
        # When params is missing, lists all operations
        assert "operations" in resp["result"]["data"]

    def test_notification_no_id_no_response(self, tmp_path):
        # JSON-RPC notifications (no id) should produce no response
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "which",
               "params": {"op": "license"}}
        resp = handle_request(req, prof)
        assert resp is None

    def test_method_registry_lists_known_methods(self):
        # Phase 1+ commands should be reachable through RPC
        for required in ("status", "version", "license", "metrics",
                         "ports", "logs", "alerts", "health",
                         "namespaces", "which", "config_show"):
            assert required in METHODS, f"missing method: {required}"


# ----------------- serve (loop) -----------------


class TestServe:
    def test_single_request_response(self, tmp_path):
        prof = _profile(tmp_path)
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "method": "which",
                        "params": {"op": "license"}, "id": 1}) + "\n"
        )
        stdout = io.StringIO()
        serve(prof, stdin=stdin, stdout=stdout)
        line = stdout.getvalue().strip()
        resp = json.loads(line)
        assert resp["id"] == 1
        assert "result" in resp

    def test_multiple_requests_each_one_line(self, tmp_path):
        prof = _profile(tmp_path)
        reqs = [
            {"jsonrpc": "2.0", "method": "which",
             "params": {"op": "license"}, "id": 1},
            {"jsonrpc": "2.0", "method": "which",
             "params": {"op": "exec"}, "id": 2},
        ]
        stdin = io.StringIO("\n".join(json.dumps(r) for r in reqs) + "\n")
        stdout = io.StringIO()
        serve(prof, stdin=stdin, stdout=stdout)
        lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == 1
        assert json.loads(lines[1])["id"] == 2

    def test_invalid_json_emits_parse_error(self, tmp_path):
        prof = _profile(tmp_path)
        stdin = io.StringIO("not json\n")
        stdout = io.StringIO()
        serve(prof, stdin=stdin, stdout=stdout)
        line = stdout.getvalue().strip()
        resp = json.loads(line)
        assert resp["error"]["code"] == -32700  # parse error

    def test_blank_lines_skipped(self, tmp_path):
        prof = _profile(tmp_path)
        stdin = io.StringIO(
            "\n\n" +
            json.dumps({"jsonrpc": "2.0", "method": "which",
                        "params": {"op": "license"}, "id": 1}) + "\n"
        )
        stdout = io.StringIO()
        serve(prof, stdin=stdin, stdout=stdout)
        lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 1


@pytest.mark.integration
class TestRpcLive:
    def test_license_via_rpc(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "license", "id": 1}
        resp = handle_request(req, prof)
        env = resp["result"]
        assert env["ok"] is True
        assert "consumed" in env["data"]

    def test_status_via_rpc(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        req = {"jsonrpc": "2.0", "method": "status", "id": 1}
        resp = handle_request(req, prof)
        assert resp["result"]["ok"] is True
