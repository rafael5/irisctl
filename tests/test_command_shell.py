"""Tests for `irisctl shell`.

The shell subcommand replaces the calling process with `docker exec -it
<container> iris session IRIS -U <namespace>` so the user's terminal
connects directly. The non-interactive paths we can test are:
- license pre-check refusal
- container-missing error
- the exec args we'd hand to os.execvp (via `build_exec_argv`)
"""

from __future__ import annotations

import pytest

from irisctl.commands.shell import build_exec_argv
from irisctl.commands.shell import run as shell_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


class TestBuildArgv:
    def test_default_namespace(self, tmp_path):
        prof = _profile(tmp_path)
        argv = build_exec_argv(prof, namespace="%SYS")
        assert argv[0] == "docker"
        assert "exec" in argv
        assert "-it" in argv
        assert prof.container in argv
        assert "iris" in argv
        assert "session" in argv
        assert "IRIS" in argv
        # Namespace passed via -U
        idx_u = argv.index("-U")
        assert argv[idx_u + 1] == "%SYS"

    def test_namespace_choice(self, tmp_path):
        prof = _profile(tmp_path)
        argv = build_exec_argv(prof, namespace="VISTA")
        idx_u = argv.index("-U")
        assert argv[idx_u + 1] == "VISTA"


class TestShellGuards:
    def test_missing_container_returns_envelope(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        env = shell_run(prof, namespace="%SYS", dry_run=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"

    @pytest.mark.integration
    def test_dry_run_returns_argv(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = shell_run(prof, namespace="%SYS", dry_run=True)
        assert env["ok"] is True
        assert env["data"]["namespace"] == "%SYS"
        assert env["data"]["argv"][0] == "docker"
        # License snapshot is included in the warning when LUs are tight
        assert "license" in env["data"]
