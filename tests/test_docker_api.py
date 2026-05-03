"""Tests for the Docker wrapper.

Phase 1 only needs read-only operations: inspect, ps-state, label-lookup,
log-tail-via-root-helper. No `docker exec` here — that's a Phase 2 concern.
"""

from __future__ import annotations

import pytest

from irisctl.docker_api import (
    DockerError,
    container_exists,
    container_state,
    image_labels,
    inspect_container,
    list_published_ports,
    tail_log_via_helper,
)

# ----------------- Live integration tests against foia -----------------


@pytest.mark.integration
class TestInspect:
    def test_container_exists(self, live_iris):
        assert container_exists(live_iris) is True

    def test_container_does_not_exist(self):
        assert container_exists("definitely-not-a-real-container-xyz") is False

    def test_state_is_running(self, live_iris):
        s = container_state(live_iris)
        assert s["status"] == "running"
        assert s["running"] is True
        # health may be 'healthy', 'unhealthy', or 'none' depending on phase
        assert "health" in s

    def test_inspect_returns_dict(self, live_iris):
        info = inspect_container(live_iris)
        assert info["Name"].endswith(live_iris)
        assert info["Config"]["User"] == "51773"
        assert "Image" in info

    def test_image_labels_have_iris_metadata(self, live_iris):
        labels = image_labels(live_iris)
        assert "com.intersystems.platform-version" in labels
        assert labels.get("name") == "IRIS"
        assert "com.intersystems.product-timestamp" in labels

    def test_published_ports_includes_iris_listeners(self, live_iris):
        ports = list_published_ports(live_iris)
        # ports is a list of dicts: [{container_port, host_port, proto}]
        host_ports = {p["host_port"] for p in ports if p.get("host_port")}
        assert 1972 in host_ports
        assert 52773 in host_ports

    def test_tail_log_via_helper(self, live_iris):
        # The mgr volume is at ~/data/foia-iris (per project_docker_vista.md)
        out = tail_log_via_helper(
            host_path="/home/rafael/data/foia-iris/mgr/messages.log",
            tail=20,
        )
        assert isinstance(out, str)
        assert len(out) > 0


# ----------------- Unit: error handling -----------------


class TestErrorPaths:
    def test_inspect_missing_container_raises(self):
        with pytest.raises(DockerError):
            inspect_container("definitely-not-a-real-container-xyz")

    def test_state_of_missing_container_raises(self):
        with pytest.raises(DockerError):
            container_state("definitely-not-a-real-container-xyz")
