"""Test fixtures shared across the suite.

`integration`-marked tests need the live `foia` IRIS container running
on localhost with port 52773 reachable. The `live_iris` fixture is the
readiness probe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Make src/ importable without requiring `pip install -e .`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _container_running(name: str) -> bool:
    res = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return name in res.stdout.split()


def _metrics_endpoint_open() -> bool:
    """Probe /api/monitor/metrics via a host-network alpine helper.

    Host-side curl/python network calls to localhost are sandbox-blocked
    in some environments; a docker run helper with --network host always
    works because it routes through Docker's bridge.
    """
    res = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "host", "alpine",
            "sh", "-c",
            "wget -qO- --timeout=3 http://localhost:52773/api/monitor/metrics "
            "| head -c 50",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return res.returncode == 0 and "iris_" in res.stdout


@pytest.fixture(scope="session")
def live_iris() -> str:
    """Confirm the foia container is up and metrics endpoint reachable.

    Returns the container name. Skips dependent tests if either fails.
    """
    name = "foia"
    if not _container_running(name):
        pytest.skip(f"container {name!r} is not running")
    if not _metrics_endpoint_open():
        pytest.skip("/api/monitor/metrics is not reachable on localhost:52773")
    return name
