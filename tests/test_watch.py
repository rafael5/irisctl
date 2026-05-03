"""Tests for the --watch loop that polls a runner repeatedly."""

from __future__ import annotations

import io

import pytest

from irisctl.watch import watch_loop


class TestWatchLoop:
    def test_runs_at_least_once(self):
        calls = []

        def runner():
            calls.append(1)
            return {"v": 1, "ok": True, "command": "x", "data": {"i": len(calls)}}

        out = io.StringIO()
        watch_loop(runner, interval=0.01, max_iters=3, out=out, render="json")
        assert len(calls) == 3
        # Three lines emitted
        lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_stops_at_max_iters(self):
        calls = []

        def runner():
            calls.append(1)
            return {"v": 1, "ok": True, "command": "x", "data": {}}

        out = io.StringIO()
        watch_loop(runner, interval=0.01, max_iters=5, out=out, render="json")
        assert len(calls) == 5

    def test_returns_last_envelope(self):
        def runner():
            return {"v": 1, "ok": True, "command": "x", "data": {"k": 42}}

        out = io.StringIO()
        last = watch_loop(runner, interval=0.01, max_iters=2, out=out,
                          render="json")
        assert last["data"]["k"] == 42

    def test_keyboard_interrupt_returns_last_envelope(self):
        # Simulate Ctrl-C on second iteration
        calls = []

        def runner():
            calls.append(1)
            if len(calls) >= 2:
                raise KeyboardInterrupt()
            return {"v": 1, "ok": True, "command": "x", "data": {"i": len(calls)}}

        out = io.StringIO()
        last = watch_loop(runner, interval=0.01, max_iters=10, out=out,
                          render="json")
        assert last is not None
        assert last["data"]["i"] == 1  # the successful call before Ctrl-C

    def test_human_render(self):
        def runner():
            return {"v": 1, "ok": True, "command": "x",
                    "data": {"foo": "bar"}, "warnings": []}

        out = io.StringIO()
        watch_loop(runner, interval=0.01, max_iters=1, out=out, render="human")
        body = out.getvalue()
        assert "foo" in body
        assert "bar" in body


@pytest.mark.integration
class TestWatchAgainstLive:
    def test_license_watch_two_iters(self, live_iris, tmp_path):
        from irisctl.commands.license import run as license_run
        from irisctl.config import load_profile

        prof = load_profile(config_path=tmp_path / "missing.toml")
        out = io.StringIO()
        last = watch_loop(lambda: license_run(prof),
                          interval=0.05, max_iters=2,
                          out=out, render="json")
        assert last["ok"] is True
        # Two JSON envelopes printed
        lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 2
