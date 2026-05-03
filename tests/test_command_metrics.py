"""Tests for the `metrics` subcommand and its sub-verbs."""

from __future__ import annotations

import argparse

import pytest

from irisctl.commands.metrics import describe, dispatch, list_metrics, scrape
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestListMetrics:
    def test_returns_metric_records(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = list_metrics(prof, prefix=None)
        assert env["ok"] is True
        assert env["command"] == "metrics"
        rows = env["data"]
        assert isinstance(rows, list)
        assert len(rows) > 50  # surface doc says ~107
        # Every row has the expected keys
        for r in rows[:5]:
            assert {"name", "help", "type", "labels", "value"} <= set(r)

    def test_prefix_filter(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = list_metrics(prof, prefix="iris_license_")
        rows = env["data"]
        assert len(rows) >= 4
        assert all(r["name"].startswith("iris_license_") for r in rows)


@pytest.mark.integration
class TestDescribe:
    def test_known_metric(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = describe(prof, "iris_license_consumed")
        assert env["ok"] is True
        d = env["data"]
        assert d["name"] == "iris_license_consumed"
        assert "help" in d
        assert "value" in d

    def test_unknown_metric_returns_not_found(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = describe(prof, "iris_definitely_not_a_metric")
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"


@pytest.mark.integration
class TestScrape:
    def test_returns_raw_text(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = scrape(prof)
        assert env["ok"] is True
        text = env["data"]["raw"]
        assert "iris_license_consumed" in text
        assert "# HELP" in text


class TestDispatch:
    def test_routes_default_to_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")  # closed
        prof = _profile(tmp_path)
        ns = argparse.Namespace(metrics_sub=None, prefix=None, name=None)
        env = dispatch(ns, prof)
        # Will fail with network_error, but the call shape is confirmed
        assert env["command"] == "metrics"

    def test_describe_branch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_HOST", "127.0.0.1")
        monkeypatch.setenv("IRISCTL_WEB_PORT", "1")
        prof = _profile(tmp_path)
        ns = argparse.Namespace(metrics_sub="describe", prefix=None,
                                name="iris_x")
        env = dispatch(ns, prof)
        # describe routes through list -> network error
        assert env["command"] == "metrics"
