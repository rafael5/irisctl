"""Tests for the HTTP client wrapping IRIS /api/monitor/* endpoints.

Integration tests hit the live foia container; unit tests cover parser
edge cases without network.
"""

from __future__ import annotations

import pytest

from irisctl.http_api import (
    IrisHttpClient,
    Metric,
    parse_prometheus,
)

# ----------------- Unit: Prometheus parser -----------------


class TestParsePrometheus:
    def test_simple_gauge(self):
        text = "\n".join([
            "# HELP iris_license_consumed Licenses in use",
            "# TYPE iris_license_consumed gauge",
            "iris_license_consumed 1",
        ])
        out = parse_prometheus(text)
        assert len(out) == 1
        m = out[0]
        assert m.name == "iris_license_consumed"
        assert m.help == "Licenses in use"
        assert m.type == "gauge"
        assert m.value == 1.0
        assert m.labels == {}

    def test_with_labels(self):
        text = "\n".join([
            "# HELP iris_csp_activity Web requests",
            "# TYPE iris_csp_activity gauge",
            'iris_csp_activity{id="127.0.0.1:52773"} 0',
        ])
        out = parse_prometheus(text)
        assert len(out) == 1
        assert out[0].labels == {"id": "127.0.0.1:52773"}
        assert out[0].value == 0.0

    def test_multiple_labels(self):
        text = (
            '# HELP m M\n'
            '# TYPE m gauge\n'
            'm{a="1",b="two"} 42\n'
        )
        out = parse_prometheus(text)
        assert out[0].labels == {"a": "1", "b": "two"}
        assert out[0].value == 42.0

    def test_blank_lines_and_comments_ignored(self):
        text = "\n".join([
            "",
            "# random comment not HELP or TYPE",
            "# HELP x x",
            "# TYPE x gauge",
            "",
            "x 5",
        ])
        out = parse_prometheus(text)
        assert len(out) == 1
        assert out[0].value == 5.0

    def test_help_after_value_does_not_overwrite(self):
        # If a name has no preceding HELP, help is empty string.
        text = "x 5"
        out = parse_prometheus(text)
        assert out[0].help == ""
        assert out[0].type == ""

    def test_float_values(self):
        text = "# HELP d d\n# TYPE d gauge\nd 3.14\n"
        assert parse_prometheus(text)[0].value == pytest.approx(3.14)

    def test_repeated_metric_with_different_labels(self):
        text = (
            "# HELP cpu cpu\n"
            "# TYPE cpu gauge\n"
            'cpu{p="A"} 1\n'
            'cpu{p="B"} 2\n'
        )
        out = parse_prometheus(text)
        assert len(out) == 2
        assert {m.labels["p"] for m in out} == {"A", "B"}


# ----------------- Integration: live container -----------------


@pytest.mark.integration
class TestIrisHttpClientLive:
    def test_metrics_returns_known_counters(self, live_iris):
        client = IrisHttpClient(base_url="http://localhost:52773")
        metrics = client.metrics()
        names = {m.name for m in metrics}
        # Pick a handful of well-known counters from the surface doc §7
        for required in [
            "iris_license_consumed",
            "iris_license_available",
            "iris_license_percent_used",
            "iris_system_state",
        ]:
            assert required in names, f"missing {required}"

    def test_metrics_raw_is_text(self, live_iris):
        client = IrisHttpClient(base_url="http://localhost:52773")
        text = client.metrics_raw()
        assert text.startswith("# HELP ") or "# HELP " in text[:200]
        assert "iris_license_consumed" in text

    def test_metrics_filter_by_prefix(self, live_iris):
        client = IrisHttpClient(base_url="http://localhost:52773")
        metrics = client.metrics(prefix="iris_license_")
        assert len(metrics) >= 4  # consumed, available, percent_used, days_remaining
        assert all(m.name.startswith("iris_license_") for m in metrics)

    def test_alerts_returns_json(self, live_iris):
        client = IrisHttpClient(base_url="http://localhost:52773")
        alerts = client.alerts()
        # Endpoint returns either a list of alerts or an empty payload
        assert isinstance(alerts, (list, dict))


# ----------------- Unit: behavior on unreachable host -----------------


class TestNetworkErrors:
    def test_unreachable_host_raises_network_error(self):
        from irisctl.http_api import NetworkError
        client = IrisHttpClient(base_url="http://127.0.0.1:1", timeout=0.5)
        with pytest.raises(NetworkError):
            client.metrics_raw()


# ----------------- Metric helper -----------------


class TestMetric:
    def test_label_lookup_default(self):
        m = Metric(name="x", help="", type="", labels={"a": "1"}, value=0)
        assert m.labels.get("a") == "1"
        assert m.labels.get("missing") is None
