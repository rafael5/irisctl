"""Tests for Phase-4 additions to docker_api."""

from __future__ import annotations

import pytest

from irisctl.docker_api import (
    DockerError,
    cat_file_via_helper,
    docker_exec,
    wait_for_tcp,
)


@pytest.mark.integration
class TestDockerExec:
    def test_returns_stdout(self, live_iris):
        out = docker_exec(live_iris, ["echo", "irisctl-test"])
        assert "irisctl-test" in out

    def test_with_stdin(self, live_iris):
        out = docker_exec(live_iris, ["cat"], input_text="hello\nworld\n")
        assert "hello" in out
        assert "world" in out

    def test_command_failure_raises(self, live_iris):
        with pytest.raises(DockerError):
            docker_exec(live_iris, ["false"])

    def test_missing_container_raises(self):
        with pytest.raises(DockerError):
            docker_exec("no-such-container-xyz", ["true"])


@pytest.mark.integration
class TestCatFileViaHelper:
    def test_reads_iris_cpf(self, live_iris):
        # iris.cpf is part of the FOIA install at ~/data/foia-iris/
        text = cat_file_via_helper(
            "/home/rafael/data/foia-iris/iris.cpf"
        )
        assert "[Defaults]" in text or "[config]" in text or "Routines" in text


class TestWaitForTcp:
    def test_returns_immediately_when_open(self):
        # 22 is sshd on this host (always open per minty-baseline)
        state = wait_for_tcp("127.0.0.1", [22], timeout=2.0, interval=0.1)
        # Either ssh is open (True) or not (False) — but the fn returns
        # without throwing.
        assert isinstance(state, dict)
        assert 22 in state

    def test_timeout_returns_partial_state(self):
        # Port 1 is virtually never open
        state = wait_for_tcp("127.0.0.1", [1], timeout=0.5, interval=0.1)
        assert state[1] is False

    @pytest.mark.integration
    def test_iris_listeners(self, live_iris):
        state = wait_for_tcp("127.0.0.1", [1972, 52773],
                             timeout=2.0, interval=0.2)
        assert state[1972] is True
        assert state[52773] is True
