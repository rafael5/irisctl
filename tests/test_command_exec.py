"""Tests for `irisctl exec`."""

from __future__ import annotations

import pytest

from irisctl.commands.exec_cmd import run as exec_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestExecLive:
    def test_simple_inline(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS",
                       script='W "irisctl-exec-test",!')
        assert env["ok"] is True
        assert env["command"] == "exec"
        assert "irisctl-exec-test" in env["data"]["output"]
        assert env["data"]["namespace"] == "%SYS"

    def test_namespace_change(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS", script='W $NAMESPACE,!')
        assert "%SYS" in env["data"]["output"]

    def test_stdin_payload(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS",
                       stdin_text='S a=2\nS b=3\nW a*b,!')
        assert env["ok"] is True
        assert "6" in env["data"]["output"]

    def test_iris_syntax_error_returns_iris_error_envelope(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS",
                       script='THIS IS NOT VALID OBJECTSCRIPT')
        assert env["ok"] is False
        assert env["error"]["code"] == "iris_error"

    def test_file_argument(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        f = tmp_path / "snippet.m"
        f.write_text('W "from-file",!\nHALT\n', encoding="utf-8")
        env = exec_run(prof, namespace="%SYS", file=f)
        assert env["ok"] is True
        assert "from-file" in env["data"]["output"]


class TestExecValidation:
    def test_missing_payload_returns_usage_error(self, tmp_path):
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_unknown_container_returns_iris_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS",
                       script='W "x",!', force=True)
        assert env["ok"] is False
        assert env["error"]["code"] in ("iris_error", "docker_error")


class TestExecLicenseGuard:
    def test_force_flag_skips_precheck(self, live_iris, tmp_path):
        # When --force is passed we should not refuse even if budget is tight.
        prof = _profile(tmp_path)
        env = exec_run(prof, namespace="%SYS",
                       script='W "ok",!', force=True)
        assert env["ok"] is True
