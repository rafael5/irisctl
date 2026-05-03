"""Tests for `irisctl logs`."""

from __future__ import annotations

import pytest

from irisctl.commands.logs import run as logs_run
from irisctl.config import load_profile


@pytest.mark.integration
class TestLogsLive:
    def test_returns_log_text(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = logs_run(prof, tail=20)
        assert env["ok"] is True
        d = env["data"]
        assert "lines" in d
        assert "path" in d
        assert d["path"].endswith("messages.log")
        assert isinstance(d["lines"], list)
        # The IRIS messages.log always has at least one entry per boot.
        assert len(d["lines"]) > 0
        # Lines look like log entries
        sample = "\n".join(d["lines"])
        assert "IRIS" in sample or "[" in sample

    def test_tail_limit(self, live_iris, tmp_path):
        prof = load_profile(config_path=tmp_path / "missing.toml")
        env = logs_run(prof, tail=5)
        assert env["ok"] is True
        assert len(env["data"]["lines"]) <= 5
