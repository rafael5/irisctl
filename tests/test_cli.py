"""Tests for the CLI top-level scaffold.

These exercise the subprocess invocation surface — argparse, --human /
--json switching, exit codes, and global flag handling — for the
single `version` command. Per-command behavior is tested separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _run(args: list[str], env_extra: dict[str, str] | None = None,
         expect_returncode: int | None = None) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    if env_extra:
        env.update(env_extra)
    res = subprocess.run(
        [sys.executable, "-m", "irisctl", *args],
        capture_output=True, text=True, env=env, timeout=30,
    )
    if expect_returncode is not None:
        assert res.returncode == expect_returncode, (
            f"expected rc={expect_returncode}, got {res.returncode}\n"
            f"stdout: {res.stdout}\nstderr: {res.stderr}"
        )
    return res


class TestUsage:
    def test_no_args_shows_usage_and_exits_2(self):
        res = _run([])
        assert res.returncode == 2
        # argparse writes usage to stderr
        assert "usage" in res.stderr.lower()

    def test_unknown_subcommand_exits_2(self):
        res = _run(["nonsense"])
        assert res.returncode == 2

    def test_help_lists_subcommands(self):
        res = _run(["--help"])
        assert res.returncode == 0
        # Phase 1
        for known in ("license", "metrics", "ports", "version", "status",
                      "logs", "health", "alerts"):
            assert known in res.stdout
        # Phase 2
        for known in ("exec", "sql", "shell"):
            assert known in res.stdout
        # Phase 3
        for known in ("namespaces", "source"):
            assert known in res.stdout
        # Phase 4
        for known in ("start", "stop", "restart", "recreate",
                      "backup", "restore", "config"):
            assert known in res.stdout


class TestGlobalFlags:
    @pytest.mark.integration
    def test_default_output_is_compact_json(self, live_iris):
        res = _run(["license"])
        assert res.returncode == 0
        # Must be parseable JSON
        env = json.loads(res.stdout)
        assert env["v"] == 1
        assert env["ok"] is True
        # Compact: no newlines
        assert res.stdout.count("\n") <= 1

    @pytest.mark.integration
    def test_human_flag_renders_table(self, live_iris):
        res = _run(["license", "--human"])
        assert res.returncode == 0
        # Not JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(res.stdout)
        # Has license fields
        assert "consumed" in res.stdout

    @pytest.mark.integration
    def test_pretty_flag_indents_json(self, live_iris):
        res = _run(["--pretty", "license"])
        assert res.returncode == 0
        env = json.loads(res.stdout)
        assert env["ok"] is True
        # Pretty: multi-line
        assert res.stdout.count("\n") >= 3
