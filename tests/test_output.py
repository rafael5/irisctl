"""Tests for the output envelope module.

The envelope is the single shape every irisctl subcommand emits.
Exit codes are part of the contract — they map 1:1 to error codes.
"""

from __future__ import annotations

import json

import pytest

from irisctl.output import (
    ErrorCode,
    error_envelope,
    exit_code_for,
    render_human,
    render_json,
    success_envelope,
)


class TestSuccessEnvelope:
    def test_minimal_shape(self):
        env = success_envelope("license", {"consumed": 1})
        assert env["v"] == 1
        assert env["ok"] is True
        assert env["command"] == "license"
        assert env["data"] == {"consumed": 1}
        assert env["warnings"] == []

    def test_with_warnings(self):
        env = success_envelope("status", {}, warnings=["unhealthy_flag_set"])
        assert env["warnings"] == ["unhealthy_flag_set"]

    def test_data_can_be_a_list(self):
        env = success_envelope("metrics", [{"name": "x", "value": 1}])
        assert env["data"] == [{"name": "x", "value": 1}]


class TestErrorEnvelope:
    def test_minimal_shape(self):
        env = error_envelope(
            "exec",
            code=ErrorCode.LICENSE_EXHAUSTED,
            message="No LUs free",
        )
        assert env["v"] == 1
        assert env["ok"] is False
        assert env["command"] == "exec"
        assert env["error"]["code"] == "license_exhausted"
        assert env["error"]["message"] == "No LUs free"
        # hint and ref are optional but the keys exist
        assert "hint" in env["error"]
        assert "ref" in env["error"]

    def test_with_hint_and_ref(self):
        env = error_envelope(
            "exec",
            code=ErrorCode.LICENSE_EXHAUSTED,
            message="No LUs free",
            hint="irisctl license users",
            ref="docs/iris-cli-surface.md#10-gotchas",
        )
        assert env["error"]["hint"] == "irisctl license users"
        assert env["error"]["ref"].endswith("#10-gotchas")


class TestExitCodes:
    def test_ok_is_zero(self):
        assert exit_code_for(ErrorCode.OK) == 0

    def test_per_plan_section_4(self):
        # Mapping pinned by docs/iris-cli-plan.md §4.3
        assert exit_code_for(ErrorCode.INTERNAL) == 1
        assert exit_code_for(ErrorCode.USAGE) == 2
        assert exit_code_for(ErrorCode.INSTANCE_NOT_RUNNING) == 3
        assert exit_code_for(ErrorCode.LICENSE_EXHAUSTED) == 4
        assert exit_code_for(ErrorCode.AUTH_REQUIRED) == 5
        assert exit_code_for(ErrorCode.AUTH_FAILED) == 5
        assert exit_code_for(ErrorCode.NOT_FOUND) == 6
        assert exit_code_for(ErrorCode.IRIS_ERROR) == 7
        assert exit_code_for(ErrorCode.DOCKER_ERROR) == 8
        assert exit_code_for(ErrorCode.NETWORK_ERROR) == 9


class TestRenderJson:
    def test_renders_canonical(self):
        env = success_envelope("license", {"consumed": 1})
        out = render_json(env)
        # round-trip must preserve shape
        assert json.loads(out) == env

    def test_compact_by_default(self):
        env = success_envelope("license", {"consumed": 1})
        out = render_json(env)
        assert "\n" not in out  # one-line by default

    def test_pretty(self):
        env = success_envelope("license", {"consumed": 1})
        out = render_json(env, pretty=True)
        assert "\n" in out


class TestRenderHuman:
    def test_success_dict_data(self):
        env = success_envelope("license", {"consumed": 1, "available": 7})
        out = render_human(env)
        assert "consumed" in out
        assert "1" in out
        assert "available" in out
        assert "7" in out

    def test_success_list_data(self):
        env = success_envelope(
            "ports",
            [{"port": 1972, "open": True}, {"port": 8001, "open": False}],
        )
        out = render_human(env)
        # Both ports surface in the output
        assert "1972" in out
        assert "8001" in out

    def test_error(self):
        env = error_envelope(
            "exec", code=ErrorCode.LICENSE_EXHAUSTED, message="No LUs free"
        )
        out = render_human(env)
        assert "ERROR" in out.upper()
        assert "license_exhausted" in out
        assert "No LUs free" in out

    def test_warnings_attached_to_success(self):
        env = success_envelope("status", {"ok": True}, warnings=["foo"])
        out = render_human(env)
        assert "foo" in out


@pytest.mark.parametrize("code,expected_string", [
    (ErrorCode.OK, "ok"),
    (ErrorCode.LICENSE_EXHAUSTED, "license_exhausted"),
    (ErrorCode.AUTH_REQUIRED, "auth_required"),
    (ErrorCode.NETWORK_ERROR, "network_error"),
])
def test_error_code_string_form(code, expected_string):
    """Error codes serialize to lowercase_underscore strings (per plan §4)."""
    assert code.value == expected_string
