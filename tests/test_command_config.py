"""Tests for `irisctl config show` and `irisctl config merge`."""

from __future__ import annotations

import argparse

import pytest

from irisctl.commands.config_cmd import dispatch, merge_run, show_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestConfigShow:
    def test_returns_cpf_text(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = show_run(prof)
        assert env["ok"] is True
        d = env["data"]
        assert "path" in d
        assert "text" in d
        assert "size_bytes" in d
        # iris.cpf has well-known section headers
        assert "[" in d["text"] and "]" in d["text"]
        assert d["size_bytes"] > 100

    def test_data_path_matches_profile(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = show_run(prof)
        # Profile data_dir is ~/data/foia-iris; iris.cpf lives at that root
        assert "iris.cpf" in env["data"]["path"]


@pytest.mark.integration
class TestConfigMergeGuards:
    def test_missing_file_returns_usage(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = merge_run(prof, file=tmp_path / "does-not-exist.cpf")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_dry_run_returns_planned_steps(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        f = tmp_path / "fragment.cpf"
        f.write_text("[Defaults]\nFakeKey=42\n", encoding="utf-8")
        env = merge_run(prof, file=f, dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        assert "steps" in env["data"]
        # Steps include: docker cp + iris merge
        joined = "\n".join(env["data"]["steps"])
        assert "docker cp" in joined
        assert "iris merge" in joined


class TestDispatch:
    def test_routes_show(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        ns = argparse.Namespace(config_sub="show")
        env = dispatch(ns, prof)
        # Will fail with docker_error since container doesn't exist;
        # but it should be 'config' command and have routed correctly
        assert env["command"] == "config"

    def test_no_subverb_returns_usage(self, tmp_path):
        prof = _profile(tmp_path)
        ns = argparse.Namespace(config_sub=None)
        env = dispatch(ns, prof)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
