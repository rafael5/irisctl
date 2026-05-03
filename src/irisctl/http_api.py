"""HTTP client for IRIS /api/monitor/* and related endpoints.

Wraps httpx with IRIS-specific helpers + a Prometheus-text parser. The
metrics + alerts endpoints are unauthenticated on the foia Community
image; auth-gated endpoints (Atelier) raise AuthRequired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx


class NetworkError(Exception):
    """Endpoint unreachable / connection failed."""


class AuthRequired(Exception):
    """401 from IRIS — caller must supply credentials."""


@dataclass
class Metric:
    name: str
    help: str
    type: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "help": self.help,
            "type": self.type,
            "labels": self.labels,
            "value": self.value,
        }


_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_prometheus(text: str) -> list[Metric]:
    """Parse Prometheus / OpenMetrics text-exposition format.

    Handles `# HELP name desc` and `# TYPE name kind` comment lines and
    plain or labelled metric samples. Returns one Metric per sample.
    """
    helps: dict[str, str] = {}
    types: dict[str, str] = {}
    out: list[Metric] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# HELP "):
            rest = line[len("# HELP "):].split(maxsplit=1)
            if len(rest) == 2:
                helps[rest[0]] = rest[1]
            elif rest:
                helps[rest[0]] = ""
            continue
        if line.startswith("# TYPE "):
            rest = line[len("# TYPE "):].split(maxsplit=1)
            if len(rest) == 2:
                types[rest[0]] = rest[1]
            continue
        if line.startswith("#"):
            continue

        # Sample line: name[{labels}] value [timestamp]
        m = _parse_sample(line)
        if m is None:
            continue
        m.help = helps.get(m.name, "")
        m.type = types.get(m.name, "")
        out.append(m)
    return out


def _parse_sample(line: str) -> Metric | None:
    if "{" in line:
        head, _, rest = line.partition("{")
        labels_str, _, value_str = rest.partition("}")
        labels = dict(_LABEL_RE.findall(labels_str))
        value_part = value_str.strip().split()
        if not value_part:
            return None
        try:
            value = float(value_part[0])
        except ValueError:
            return None
        return Metric(name=head.strip(), help="", type="", labels=labels, value=value)
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        value = float(parts[1])
    except ValueError:
        return None
    return Metric(name=parts[0], help="", type="", labels={}, value=value)


class IrisHttpClient:
    """Thin httpx wrapper for IRIS HTTP endpoints."""

    def __init__(
        self,
        base_url: str = "http://localhost:52773",
        timeout: float = 5.0,
        auth: tuple[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auth = auth

    def _get(self, path: str, *, accept: str = "*/*") -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            res = httpx.get(
                url,
                timeout=self.timeout,
                auth=self.auth,
                headers={"Accept": accept},
            )
        except httpx.RequestError as e:
            raise NetworkError(f"{url}: {e}") from e
        if res.status_code == 401:
            raise AuthRequired(f"{url}: 401")
        res.raise_for_status()
        return res

    def metrics_raw(self) -> str:
        return self._get("/api/monitor/metrics", accept="text/plain").text

    def metrics(self, *, prefix: str | None = None) -> list[Metric]:
        out = parse_prometheus(self.metrics_raw())
        if prefix is not None:
            out = [m for m in out if m.name.startswith(prefix)]
        return out

    def alerts(self) -> Any:
        res = self._get("/api/monitor/alerts", accept="application/json")
        ct = res.headers.get("content-type", "")
        if "json" in ct:
            return res.json()
        # Some builds return text; downgrade to a dict so callers can rely
        # on the type contract.
        body = res.text.strip()
        if not body:
            return []
        try:
            import json
            return json.loads(body)
        except ValueError:
            return {"raw": body}
