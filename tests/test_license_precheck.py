"""Tests for the license pre-check helper.

Used by every LU-consuming Phase 2 subcommand to refuse work when the
LU budget is too tight.
"""

from __future__ import annotations

import pytest

from irisctl.config import load_profile
from irisctl.license import LicenseStatus, fetch_status, precheck


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- fetch_status against live container -----------------


@pytest.mark.integration
class TestFetchStatusLive:
    def test_returns_status_record(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        s = fetch_status(prof)
        assert isinstance(s, LicenseStatus)
        assert s.cap == s.consumed + s.available
        assert s.cap >= 1
        assert 0 <= s.percent_used <= 100


# ----------------- precheck logic -----------------


class TestPrecheck:
    def test_ok_when_budget_available(self):
        s = LicenseStatus(consumed=1, available=7, cap=8,
                          percent_used=13, days_remaining=327)
        # default reserve=1, op_cost=1: need available - 1 >= 1 → 7-1=6 ≥ 1 OK
        env = precheck("exec", s)
        assert env is None  # None means "go ahead"

    def test_blocks_when_at_reserve(self):
        s = LicenseStatus(consumed=7, available=1, cap=8,
                          percent_used=88, days_remaining=327)
        # available=1, op_cost=1, reserve=1 → 1-1=0 < 1 → block
        env = precheck("exec", s, op_cost=1, reserve=1)
        assert env is not None
        assert env["ok"] is False
        assert env["error"]["code"] == "license_exhausted"

    def test_force_bypasses(self):
        s = LicenseStatus(consumed=8, available=0, cap=8,
                          percent_used=100, days_remaining=327)
        env = precheck("exec", s, force=True)
        assert env is None

    def test_blocks_when_op_cost_too_high(self):
        s = LicenseStatus(consumed=2, available=2, cap=4,
                          percent_used=50, days_remaining=327)
        env = precheck("exec", s, op_cost=3, reserve=1)
        assert env is not None
        assert env["error"]["code"] == "license_exhausted"

    def test_error_message_includes_counts(self):
        s = LicenseStatus(consumed=7, available=0, cap=7,
                          percent_used=100, days_remaining=10)
        env = precheck("sql", s)
        assert env is not None
        msg = env["error"]["message"]
        assert "0" in msg  # available
        assert "7" in msg  # consumed or cap

    def test_command_name_propagates_to_envelope(self):
        s = LicenseStatus(consumed=8, available=0, cap=8,
                          percent_used=100, days_remaining=327)
        env = precheck("my-command", s)
        assert env["command"] == "my-command"
