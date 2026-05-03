"""Tests for `irisctl sql`."""

from __future__ import annotations

import pytest

from irisctl.commands.sql import run as sql_run
from irisctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestSqlLive:
    def test_simple_select_in_user_namespace(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = sql_run(prof, namespace="USER",
                      statement="SELECT 1 AS one, 'hello' AS s")
        assert env["ok"] is True, env
        d = env["data"]
        assert d["namespace"] == "USER"
        # Result set: at least one row, our two columns
        assert len(d["rows"]) == 1
        # Column metadata
        col_names = {c.lower() for c in d["columns"]}
        assert "one" in col_names
        assert "s" in col_names

    def test_count_query(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        # Count files in FileMan-equivalent table — every IRIS install has
        # %Dictionary.ClassDefinition with rows.
        env = sql_run(prof, namespace="%SYS",
                      statement="SELECT COUNT(*) AS n FROM %Dictionary.ClassDefinition")
        assert env["ok"] is True
        assert len(env["data"]["rows"]) == 1
        # the n column has a numeric value
        first_row = env["data"]["rows"][0]
        assert any(int(v) > 0 for v in first_row.values() if str(v).isdigit())

    def test_invalid_sql_returns_iris_error(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        env = sql_run(prof, namespace="USER",
                      statement="SELECT FROM WHERE BROKEN")
        assert env["ok"] is False
        assert env["error"]["code"] == "iris_error"
        msg = env["error"]["message"]
        assert "SQL" in msg or "syntax" in msg.lower()

    def test_quote_escape(self, live_iris, tmp_path):
        # SQL containing a literal " (escaped as "" in ObjectScript)
        prof = _profile(tmp_path)
        env = sql_run(prof, namespace="USER",
                      statement="SELECT 'a\"b' AS q")
        assert env["ok"] is True
        # Cell value preserved
        rows = env["data"]["rows"]
        assert len(rows) == 1


class TestSqlValidation:
    def test_no_payload_is_usage_error(self, tmp_path):
        prof = _profile(tmp_path)
        env = sql_run(prof, namespace="USER")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_file_payload(self, live_iris, tmp_path):
        prof = _profile(tmp_path)
        f = tmp_path / "q.sql"
        f.write_text("SELECT 42 AS answer", encoding="utf-8")
        env = sql_run(prof, namespace="USER", file=f)
        assert env["ok"] is True
        rows = env["data"]["rows"]
        assert len(rows) == 1
