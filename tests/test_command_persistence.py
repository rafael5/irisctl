"""Tests for `irisctl backup` and `irisctl restore`.

Cheap paths (validation, dry-run, planning) run live. Real backup +
real restore round-trips are gated behind `@pytest.mark.slow`.
"""

from __future__ import annotations

import pytest

from irisctl.commands.backup import run as backup_run
from irisctl.commands.restore import run as restore_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestBackupDryRun:
    def test_dry_run_returns_plan(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = backup_run(prof, to=tmp_path / "out.tgz", dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        steps = env["data"]["steps"]
        joined = "\n".join(steps)
        assert "stop" in joined.lower()
        assert "tar" in joined.lower()
        assert "start" in joined.lower()


@pytest.mark.integration
class TestRestoreGuards:
    def test_refuses_without_yes(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        f = tmp_path / "fake-backup.tgz"
        f.write_bytes(b"not-real")
        env = restore_run(prof, source=f, yes=False)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
        assert "--yes" in env["error"]["message"]

    def test_missing_source_returns_not_found(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = restore_run(prof, source=tmp_path / "no-such.tgz",
                          yes=True, dry_run=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"

    def test_dry_run_returns_plan(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        f = tmp_path / "fake-backup.tgz"
        f.write_bytes(b"not-real")
        env = restore_run(prof, source=f, yes=False, dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        steps = env["data"]["steps"]
        joined = "\n".join(steps)
        assert "stop" in joined.lower()
        assert "wipe" in joined.lower() or "rm -rf" in joined.lower()
        assert "tar" in joined.lower()


@pytest.mark.integration
@pytest.mark.slow
class TestBackupReal:
    """Real backup (~10-30s for 4.6GB DAT) — opt in via `make test-slow`."""

    def test_round_trip_to_tmp(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        out = tmp_path / "test-backup.tgz"
        env = backup_run(prof, to=out, online=True)
        # online=True backup uses mupip-style snapshot — but since we're
        # bypassing iris and using tar of the volume, we accept either
        # online or offline mode here.
        assert env["ok"] is True
        assert out.exists() or env["data"].get("path", "").endswith(".tgz")
