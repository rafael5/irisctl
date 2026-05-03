"""JSON-RPC 2.0 single-process mode.

`irisctl rpc` reads newline-delimited JSON-RPC 2.0 requests on stdin
and writes responses on stdout. Designed for AI agents that want a
persistent process to talk to instead of spawning ~28 distinct CLI
invocations — keeps the import / argparse / config-load cost amortized.

Why not a socket: stdin/stdout fits the pipe model already used by
LSP-style tools and by claude code itself; no port / auth concerns.

Why JSON-RPC 2.0: it has a stable, well-known framing (one request
object per line) and a defined error-code namespace.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any, Callable

from irisctl.commands import alerts as cmd_alerts
from irisctl.commands import backup as cmd_backup
from irisctl.commands import config_cmd as cmd_config
from irisctl.commands import docs as cmd_docs
from irisctl.commands import exec_cmd as cmd_exec
from irisctl.commands import health as cmd_health
from irisctl.commands import license as cmd_license
from irisctl.commands import lifecycle as cmd_lifecycle
from irisctl.commands import logs as cmd_logs
from irisctl.commands import metrics as cmd_metrics
from irisctl.commands import namespaces as cmd_namespaces
from irisctl.commands import portal as cmd_portal
from irisctl.commands import ports as cmd_ports
from irisctl.commands import restore as cmd_restore
from irisctl.commands import shell as cmd_shell
from irisctl.commands import source as cmd_source
from irisctl.commands import sql as cmd_sql
from irisctl.commands import status as cmd_status
from irisctl.commands import version as cmd_version
from irisctl.commands import which as cmd_which
from irisctl.config import Profile

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# Method registry: name → callable(profile, **params) → envelope
def _build_registry() -> dict[str, Callable[..., dict[str, Any]]]:
    return {
        # Phase 1 — read-only
        "status": lambda p: cmd_status.run(p),
        "version": lambda p: cmd_version.run(p),
        "ports": lambda p: cmd_ports.run(p),
        "logs": lambda p, tail=200: cmd_logs.run(p, tail=tail),
        "alerts": lambda p: cmd_alerts.run(p),
        "health": lambda p: cmd_health.run(p),
        "license": lambda p: cmd_license.run(p),
        "metrics": lambda p, prefix=None: cmd_metrics.list_metrics(p, prefix=prefix),
        "metrics_describe": lambda p, name: cmd_metrics.describe(p, name),
        "metrics_scrape": lambda p: cmd_metrics.scrape(p),
        # Phase 2 — execution
        "exec": lambda p, ns="%SYS", script=None, file=None, force=False:
                cmd_exec.run(p, namespace=ns, script=script,
                             file=Path(file) if file else None, force=force),
        "sql": lambda p, ns="USER", statement=None, file=None, force=False:
               cmd_sql.run(p, namespace=ns, statement=statement,
                           file=Path(file) if file else None, force=force),
        "shell": lambda p, ns="%SYS", force=False:
                 cmd_shell.run(p, namespace=ns, force=force, dry_run=True),
        # Phase 3 — Atelier
        "namespaces": lambda p: cmd_namespaces.run(p),
        "source_list": lambda p, namespace, pattern=None, type=None:
                       cmd_source.list_docs(p, namespace=namespace,
                                             type_=type, pattern=pattern),
        "source_get": lambda p, namespace, doc:
                      cmd_source.get(p, namespace=namespace, doc=doc),
        "source_put": lambda p, namespace, doc, content_lines:
                      cmd_source.put(p, namespace=namespace, doc=doc,
                                     content_lines=content_lines),
        "source_delete": lambda p, namespace, doc:
                         cmd_source.delete(p, namespace=namespace, doc=doc),
        "source_compile": lambda p, namespace, doc_names, flags="ck":
                          cmd_source.compile_(p, namespace=namespace,
                                               doc_names=doc_names, flags=flags),
        # Phase 4 — lifecycle + persistence
        "start": lambda p, wait_timeout=60.0:
                 cmd_lifecycle.start_run(p, wait_timeout=wait_timeout),
        "stop": lambda p, timeout=60: cmd_lifecycle.stop_run(p, timeout=timeout),
        "restart": lambda p, timeout=60, wait_timeout=60.0:
                   cmd_lifecycle.restart_run(p, timeout=timeout,
                                              wait_timeout=wait_timeout),
        "recreate": lambda p, image="foia:latest", yes=False, dry_run=False:
                    cmd_lifecycle.recreate_run(p, image=image, yes=yes,
                                                dry_run=dry_run),
        "backup": lambda p, to=None, online=True, dry_run=False:
                  cmd_backup.run(p, to=Path(to) if to else None,
                                 online=online, dry_run=dry_run),
        "restore": lambda p, source, yes=False, dry_run=False:
                   cmd_restore.run(p, source=Path(source), yes=yes,
                                    dry_run=dry_run),
        "config_show": lambda p: cmd_config.show_run(p),
        "config_merge": lambda p, file, dry_run=False:
                        cmd_config.merge_run(p, file=Path(file), dry_run=dry_run),
        # Phase 5 — convenience
        "which": lambda p, op=None: cmd_which.run(p, op=op),
        "portal": lambda p, path=None, dry_run=True:
                  cmd_portal.run(p, path=path, dry_run=dry_run),
        "docs": lambda p, key, dry_run=True:
                cmd_docs.run(p, key=key, dry_run=dry_run),
    }


METHODS = _build_registry()


def _rpc_error(req_id: Any, code: int, message: str,
                data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_request(
    req: dict[str, Any],
    profile: Profile,
) -> dict[str, Any] | None:
    """Process one JSON-RPC request; return response or None for a notification."""
    req_id = req.get("id")
    is_notification = "id" not in req

    if req.get("jsonrpc") != "2.0":
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_REQUEST,
                          "missing or invalid jsonrpc field")

    method = req.get("method")
    if not isinstance(method, str):
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_REQUEST, "missing method")

    fn = METHODS.get(method)
    if fn is None:
        if is_notification:
            return None
        return _rpc_error(req_id, METHOD_NOT_FOUND,
                          f"method {method!r} not registered",
                          data={"available": sorted(METHODS)})

    raw_params = req.get("params") or {}
    if isinstance(raw_params, list):
        # Positional params unsupported — JSON-RPC allows but our
        # registry uses named keyword args.
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_PARAMS,
                          "positional params not supported; use object form")

    try:
        result = fn(profile, **raw_params)
    except TypeError as e:
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_PARAMS, str(e))
    except Exception as e:  # noqa: BLE001
        if is_notification:
            return None
        return _rpc_error(req_id, INTERNAL_ERROR,
                          f"{type(e).__name__}: {e}")

    if is_notification:
        return None
    return _rpc_result(req_id, result)


def serve(
    profile: Profile,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> None:
    """Read newline-delimited JSON-RPC requests until EOF.

    Each request gets one response line on stdout (notifications get
    no response). Parse errors are emitted as JSON-RPC parse-error
    responses with id=null.
    """
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout

    for line in in_stream:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err = _rpc_error(None, PARSE_ERROR, f"parse error: {e}")
            out_stream.write(json.dumps(err) + "\n")
            out_stream.flush()
            continue

        if not isinstance(req, dict):
            err = _rpc_error(None, INVALID_REQUEST,
                             "request must be a JSON object (batch not supported)")
            out_stream.write(json.dumps(err) + "\n")
            out_stream.flush()
            continue

        resp = handle_request(req, profile)
        if resp is None:
            continue
        out_stream.write(json.dumps(resp, separators=(",", ":")) + "\n")
        out_stream.flush()
