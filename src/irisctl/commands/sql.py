"""`irisctl sql` — run a SQL statement and return a structured result set.

Wraps `##class(%SQL.Statement).%ExecDirect` inside `iris session` and
captures result rows + column metadata in JSON. Each call consumes 1 LU.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from irisctl.config import Profile
from irisctl.exec_session import ExecError, session_exec
from irisctl.license import fetch_and_precheck
from irisctl.output import ErrorCode, error_envelope, success_envelope


def run(
    profile: Profile,
    *,
    namespace: str = "USER",
    statement: str | None = None,
    file: Path | None = None,
    force: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    sql = _resolve_sql(statement=statement, file=file)
    if sql is None:
        return error_envelope(
            "sql",
            code=ErrorCode.USAGE,
            message="sql needs a statement: pass it inline or via --file PATH",
            hint="example: irisctl sql --ns USER 'SELECT 1'",
        )

    refusal = fetch_and_precheck("sql", profile, op_cost=1, force=force)
    if refusal is not None:
        return refusal

    script = _build_script(sql)
    try:
        out = session_exec(profile, namespace=namespace,
                           script=script, timeout=timeout)
    except ExecError as e:
        return error_envelope(
            "sql",
            code=ErrorCode.IRIS_ERROR,
            message=str(e),
            hint="check the SQL; quote/identifier escaping follows ObjectScript rules",
        )

    parsed = _parse_output(out)
    if parsed.get("error") is not None:
        return error_envelope(
            "sql",
            code=ErrorCode.IRIS_ERROR,
            message=parsed["error"],
            hint="check SQLCODE and message text",
        )

    return success_envelope("sql", {
        "namespace": namespace,
        "columns": parsed["columns"],
        "rows": parsed["rows"],
        "rowcount": len(parsed["rows"]),
    })


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_sql(*, statement: str | None, file: Path | None) -> str | None:
    if statement is not None:
        return statement
    if file is not None:
        return Path(file).read_text(encoding="utf-8")
    return None


def _escape_for_objectscript(sql: str) -> str:
    """Escape a SQL string for embedding inside an ObjectScript "..." literal.

    ObjectScript escape: literal `"` is doubled (`""`). Newlines collapse
    to spaces — multi-line SQL is supported but flattened.
    """
    flat = " ".join(sql.split())
    return flat.replace('"', '""')


def _build_script(sql: str) -> str:
    """ObjectScript wrapper around %SQL.Statement.

    Uses single-line postconditional IF and dot-block FOR for direct-mode
    reliability. Emits tab-delimited rows so the Python side can parse
    deterministically without depending on %ToJSON (which is missing on
    %SQL.StatementResult in some IRIS builds).

    Output framing (all `!`-terminated):
        IRISCTL-SQL-COLS<TAB>c1<TAB>c2...
        IRISCTL-SQL-ROW<TAB>v1<TAB>v2...      (one per row)
        IRISCTL-SQL-ROWCOUNT|<n>
    On error:
        IRISCTL-SQL-ERROR:<source>:<sqlcode>:<message>
    """
    escaped = _escape_for_objectscript(sql)
    # Build with single-line FORs: inner F's body is exactly one command
    # (the cell write); commands after that on the same line belong to
    # the outer F's body. Direct mode doesn't support dot blocks.
    return (
        f'SET sql="{escaped}"\n'
        'SET stmt=##class(%SQL.Statement).%New()\n'
        'SET sc=stmt.%Prepare(sql)\n'
        'IF $SYSTEM.Status.IsError(sc) '
        'WRITE "IRISCTL-SQL-ERROR:prepare:",'
        '$SYSTEM.Status.GetErrorText(sc),! HALT\n'
        'SET rs=stmt.%Execute()\n'
        'IF rs.%SQLCODE<0 '
        'WRITE "IRISCTL-SQL-ERROR:exec:",rs.%SQLCODE,":",rs.%Message,! HALT\n'
        'SET md=rs.%GetMetadata()\n'
        'WRITE "IRISCTL-SQL-COLS" '
        'FOR i=1:1:md.columnCount WRITE $CHAR(9),md.columns.GetAt(i).colName\n'
        'WRITE !\n'
        'SET n=0\n'
        'FOR  QUIT:\'rs.%Next()  '
        'WRITE "IRISCTL-SQL-ROW" '
        'FOR j=1:1:md.columnCount WRITE $CHAR(9),rs.%GetData(j)  '
        'WRITE !  SET n=n+1\n'
        'WRITE "IRISCTL-SQL-ROWCOUNT|",n,!\n'
        'HALT\n'
    )


_ERROR_RE = re.compile(r"IRISCTL-SQL-ERROR:(.+?)$", re.MULTILINE)


def _parse_output(out: str) -> dict[str, Any]:
    err = _ERROR_RE.search(out)
    if err:
        return {"error": err.group(1).strip(), "columns": [], "rows": []}

    columns: list[str] = []
    rows: list[dict[str, Any]] = []

    for raw_line in out.splitlines():
        if raw_line.startswith("IRISCTL-SQL-COLS"):
            parts = raw_line.split("\t")
            columns = [p for p in parts[1:] if p != ""]
        elif raw_line.startswith("IRISCTL-SQL-ROW\t") or raw_line == "IRISCTL-SQL-ROW":
            parts = raw_line.split("\t")
            cells = parts[1:]
            row: dict[str, Any] = {}
            for i, cell in enumerate(cells):
                key = columns[i] if i < len(columns) else f"c{i}"
                row[key] = cell
            rows.append(row)

    return {"error": None, "columns": columns, "rows": rows}
