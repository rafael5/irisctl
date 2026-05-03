"""Tests for `irisctl portal` and `irisctl docs`."""

from __future__ import annotations

from irisctl.commands.docs import build_docs_url
from irisctl.commands.docs import run as docs_run
from irisctl.commands.portal import build_portal_url
from irisctl.commands.portal import run as portal_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ---------------- portal ----------------


class TestPortalUrl:
    def test_default_path(self, tmp_path):
        prof = _profile(tmp_path)
        url = build_portal_url(prof, path=None)
        assert url == f"http://{prof.host}:{prof.web_port}/csp/sys/UtilHome.csp"

    def test_explicit_path(self, tmp_path):
        prof = _profile(tmp_path)
        url = build_portal_url(prof, path="op/UtilSysLicenseUse.csp")
        assert url.endswith("/csp/sys/op/UtilSysLicenseUse.csp")

    def test_strips_leading_slash(self, tmp_path):
        prof = _profile(tmp_path)
        url = build_portal_url(prof, path="/op/X.csp")
        assert url.endswith("/csp/sys/op/X.csp")
        assert "/csp/sys//op" not in url

    def test_external_path_passes_through(self, tmp_path):
        # Allow paths that already include /csp prefix
        prof = _profile(tmp_path)
        url = build_portal_url(prof, path="/csp/documatic/")
        assert url.endswith("/csp/documatic/")


class TestPortalRun:
    def test_dry_run_returns_url(self, tmp_path):
        prof = _profile(tmp_path)
        env = portal_run(prof, path=None, dry_run=True)
        assert env["ok"] is True
        assert env["data"]["url"].startswith("http://")
        assert "UtilHome" in env["data"]["url"]


# ---------------- docs ----------------


class TestDocsUrl:
    def test_uppercase_key(self):
        url = build_docs_url("ADOCK")
        assert "irislatest" in url
        assert "KEY=ADOCK" in url

    def test_strips_whitespace(self):
        url = build_docs_url("  ADOCK  ")
        assert url.endswith("KEY=ADOCK")


class TestDocsRun:
    def test_dry_run_returns_url(self, tmp_path):
        prof = _profile(tmp_path)
        env = docs_run(prof, key="ADOCK", dry_run=True)
        assert env["ok"] is True
        assert "url" in env["data"]
        assert "ADOCK" in env["data"]["url"]

    def test_missing_key_returns_usage(self, tmp_path):
        prof = _profile(tmp_path)
        env = docs_run(prof, key=None, dry_run=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
