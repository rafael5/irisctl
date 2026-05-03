"""Tests for `irisctl which <op>` — explain the underlying mechanism."""

from __future__ import annotations

from irisctl.commands.which import (
    OPERATIONS,
    describe,
)
from irisctl.commands.which import (
    run as which_run,
)
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


class TestDescribe:
    def test_known_op(self, tmp_path):
        prof = _profile(tmp_path)
        rec = describe("license", prof)
        assert rec is not None
        assert rec["op"] == "license"
        assert "mechanism" in rec
        assert "underlying" in rec
        # license routes through HTTP, no LU consumed
        assert "no_lu" in rec or rec.get("lu_cost", 1) == 0

    def test_exec_op_costs_one_lu(self, tmp_path):
        prof = _profile(tmp_path)
        rec = describe("exec", prof)
        assert rec["lu_cost"] == 1
        assert "iris session" in rec["underlying"]

    def test_unknown_op_returns_none(self, tmp_path):
        prof = _profile(tmp_path)
        assert describe("not-a-real-op", prof) is None

    def test_substitutes_profile_values(self, tmp_path):
        prof = _profile(tmp_path)
        rec = describe("license", prof)
        # The profile's web URL appears in the underlying command text
        assert prof.host in rec["underlying"]
        assert str(prof.web_port) in rec["underlying"]


class TestRun:
    def test_specific_op(self, tmp_path):
        prof = _profile(tmp_path)
        env = which_run(prof, op="license")
        assert env["ok"] is True
        assert env["data"]["op"] == "license"

    def test_unknown_op_returns_not_found(self, tmp_path):
        prof = _profile(tmp_path)
        env = which_run(prof, op="not-real")
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"

    def test_no_op_lists_all(self, tmp_path):
        prof = _profile(tmp_path)
        env = which_run(prof, op=None)
        assert env["ok"] is True
        ops = env["data"]["operations"]
        assert isinstance(ops, list)
        # All Phase 1-4 commands have entries
        names = {r["op"] for r in ops}
        for known in ("license", "exec", "sql", "source", "backup", "config"):
            assert known in names


class TestRegistry:
    def test_registry_has_phase_1_through_4(self):
        names = set(OPERATIONS.keys())
        # Phase 1
        assert {"status", "license", "metrics", "ports", "logs",
                "alerts", "version", "health"} <= names
        # Phase 2
        assert {"exec", "sql", "shell"} <= names
        # Phase 3
        assert {"namespaces", "source"} <= names
        # Phase 4
        assert {"start", "stop", "restart", "recreate",
                "backup", "restore", "config"} <= names
