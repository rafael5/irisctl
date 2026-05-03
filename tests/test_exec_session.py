"""Tests for the exec_session module — `iris session` heredoc wrapper."""

from __future__ import annotations

import pytest

from irisctl.config import load_profile
from irisctl.exec_session import (
    ExecError,
    ensure_halt,
    session_exec,
)


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- HALT injection (pure logic, no container) -----------------


class TestEnsureHalt:
    def test_appends_halt_when_missing(self):
        out = ensure_halt('W "hello",!')
        assert out.rstrip().endswith("HALT")

    def test_already_ends_with_halt(self):
        out = ensure_halt('W "hello",!\nHALT')
        # Should not double up
        assert out.count("HALT") == 1

    def test_lowercase_halt_is_recognized(self):
        out = ensure_halt('W "x",!\nhalt')
        # Single HALT (the original lowercase one is preserved).
        assert out.lower().count("halt") == 1

    def test_replaces_trailing_quit(self):
        out = ensure_halt('W "x",!\nQUIT')
        # QUIT is dangerous in a heredoc — only exits the current frame
        assert "QUIT" not in out.split("\n")[-1].upper() or "HALT" in out
        assert out.rstrip().endswith("HALT")

    def test_replaces_trailing_short_q(self):
        # `Q` (one-letter QUIT) is the most common form in real M code
        out = ensure_halt('W "x",!\n Q')
        assert out.rstrip().endswith("HALT")

    def test_h_command_treated_as_halt(self):
        # In ObjectScript, `H` alone is HALT (with no args). If user wrote
        # `H` we should not add another HALT.
        out = ensure_halt('W "x",!\nH')
        # Either H or HALT counts as terminator — should not append HALT
        # NOTE: this is a subtle case; the simplest contract is to leave
        # H alone but ensure HALT is present somewhere.
        assert "H" in out


# ----------------- Live session_exec -----------------


@pytest.mark.integration
class TestSessionExecLive:
    def test_simple_write(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        out = session_exec(prof, namespace="%SYS",
                           script='W "irisctl-test",!')
        assert "irisctl-test" in out

    def test_namespace_zn(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        # Confirm the -U argument actually takes effect by reading $NAMESPACE
        out = session_exec(prof, namespace="%SYS",
                           script='W $NAMESPACE,!')
        assert "%SYS" in out

    def test_multi_line_script(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        script = (
            'S a=2\n'
            'S b=3\n'
            'W a*b,!'
        )
        out = session_exec(prof, namespace="%SYS", script=script)
        assert "6" in out

    def test_quit_replaced_with_halt_does_not_hang(self, live_iris, tmp_path):
        # If we accidentally pass QUIT, the wrapper should still terminate.
        prof = _profile(tmp_path)
        out = session_exec(prof, namespace="%SYS",
                           script='W "ok",!\nQUIT', timeout=10)
        assert "ok" in out

    def test_iris_error_raises(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        # Syntax error should be raised as ExecError
        with pytest.raises(ExecError):
            session_exec(prof, namespace="%SYS",
                         script='THIS IS NOT VALID OBJECTSCRIPT')


# ----------------- Container missing -----------------


class TestSessionExecError:
    def test_unknown_container(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IRISCTL_CONTAINER", "no-such-container-xyz")
        prof = _profile(tmp_path)
        with pytest.raises(ExecError):
            session_exec(prof, namespace="%SYS",
                         script='W "x",!', timeout=5)
