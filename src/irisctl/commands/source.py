"""`irisctl source` — source-code CRUD via Atelier.

Sub-verbs:
- list <NS>                     — GetDocNames
- get <NS>/<doc>                — GetDoc, prints content to data.content
- put <NS>/<doc> --file PATH    — PutDoc (upsert), reads from file or stdin
- delete <NS>/<doc>             — DeleteDoc
- compile <NS> <DOC[,DOC...]>   — POST action/compile

Each operation routes through the Atelier client. Auth is resolved from
profile.resolve_auth() — env vars first, then TOML, then None (which
yields an auth_required envelope).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import httpx

from irisctl.atelier_api import AtelierClient
from irisctl.config import Profile
from irisctl.http_api import AuthRequired, NetworkError
from irisctl.output import ErrorCode, error_envelope, success_envelope


class _MissingAuth(Exception):
    """Raised by _resolve_client when no creds are configured."""


def _resolve_client(profile: Profile) -> AtelierClient:
    auth = profile.resolve_auth()
    if auth is None:
        raise _MissingAuth()
    return AtelierClient(base_url=profile.web_base_url(), auth=auth)


def _missing_auth_envelope() -> dict[str, Any]:
    return error_envelope(
        "source",
        code=ErrorCode.AUTH_REQUIRED,
        message="atelier endpoint requires credentials",
        hint=("set IRISCTL_AUTH_USER and IRISCTL_AUTH_PW "
              "(or IRISCTL_AUTH_PW_ENV)"),
    )


def _wrap(command: str, fn) -> dict[str, Any]:
    """Common error mapping for atelier calls."""
    try:
        return fn()
    except AuthRequired:
        return error_envelope(
            command,
            code=ErrorCode.AUTH_FAILED,
            message="credentials rejected by IRIS (HTTP 401)",
            hint="check IRISCTL_AUTH_USER / IRISCTL_AUTH_PW values",
        )
    except NetworkError as e:
        return error_envelope(
            command,
            code=ErrorCode.NETWORK_ERROR,
            message=str(e),
        )
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 404:
            return error_envelope(
                command,
                code=ErrorCode.NOT_FOUND,
                message=f"{e.request.url.path}: 404",
            )
        return error_envelope(
            command,
            code=ErrorCode.IRIS_ERROR,
            message=f"HTTP {code}: {e.response.text[:300]}",
        )


# ----------------- list -----------------


def list_docs(
    profile: Profile,
    *,
    namespace: str,
    type_: str | None = None,
    pattern: str | None = None,
) -> dict[str, Any]:
    try:
        client = _resolve_client(profile)
    except _MissingAuth:
        return _missing_auth_envelope()

    def call() -> dict[str, Any]:
        docs = client.get_doc_names(namespace, type_=type_, filter_=pattern)
        return success_envelope("source", {
            "namespace": namespace,
            "atelier_version": client.version,
            "docs": docs,
            "count": len(docs),
        })
    return _wrap("source", call)


# ----------------- get -----------------


def get(profile: Profile, *, namespace: str, doc: str) -> dict[str, Any]:
    try:
        client = _resolve_client(profile)
    except _MissingAuth:
        return _missing_auth_envelope()

    def call() -> dict[str, Any]:
        result = client.get_doc(namespace, doc)
        if not result.get("content"):
            return error_envelope(
                "source",
                code=ErrorCode.NOT_FOUND,
                message=f"document {namespace}/{doc} not found or empty",
            )
        return success_envelope("source", {
            "namespace": namespace,
            "name": result["name"],
            "content": result["content"],
            "lines": len(result["content"]),
            "ts": result.get("ts"),
        })
    return _wrap("source", call)


# ----------------- put -----------------


def put(
    profile: Profile,
    *,
    namespace: str,
    doc: str,
    content_lines: list[str] | None = None,
    file: Path | None = None,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    if content_lines is None:
        if file is not None:
            content_lines = Path(file).read_text(encoding="utf-8").splitlines()
        elif stdin_text is not None:
            content_lines = stdin_text.splitlines()
        else:
            return error_envelope(
                "source",
                code=ErrorCode.USAGE,
                message="put needs content: pass content_lines, --file, or --stdin",
            )

    try:
        client = _resolve_client(profile)
    except _MissingAuth:
        return _missing_auth_envelope()

    def call() -> dict[str, Any]:
        client.put_doc(namespace, doc, content_lines)
        return success_envelope("source", {
            "namespace": namespace,
            "name": doc,
            "lines_written": len(content_lines),
        })
    return _wrap("source", call)


# ----------------- delete -----------------


def delete(profile: Profile, *, namespace: str, doc: str) -> dict[str, Any]:
    try:
        client = _resolve_client(profile)
    except _MissingAuth:
        return _missing_auth_envelope()

    def call() -> dict[str, Any]:
        client.delete_doc(namespace, doc)
        return success_envelope("source", {
            "namespace": namespace,
            "name": doc,
            "deleted": True,
        })
    return _wrap("source", call)


# ----------------- compile -----------------


def compile_(
    profile: Profile,
    *,
    namespace: str,
    doc_names: list[str],
    flags: str = "ck",
) -> dict[str, Any]:
    try:
        client = _resolve_client(profile)
    except _MissingAuth:
        return _missing_auth_envelope()

    def call() -> dict[str, Any]:
        result = client.compile_docs(namespace, doc_names, flags=flags)
        result_body = result.get("result", result)
        # The result shape varies; surface the full payload + a count.
        compiled = 0
        if isinstance(result_body, dict):
            content = result_body.get("content", [])
            if isinstance(content, list):
                compiled = len(content)
        return success_envelope("source", {
            "namespace": namespace,
            "compiled": compiled,
            "flags": flags,
            "result": result,
        })
    return _wrap("source", call)


# ----------------- CLI dispatch -----------------


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "source_sub", None)
    if sub == "list":
        return list_docs(profile, namespace=args.namespace,
                         type_=getattr(args, "type", None),
                         pattern=getattr(args, "pattern", None))
    if sub == "get":
        return get(profile, namespace=args.namespace, doc=args.doc)
    if sub == "put":
        return put(profile, namespace=args.namespace, doc=args.doc,
                   file=getattr(args, "file", None),
                   stdin_text=getattr(args, "stdin_text", None))
    if sub == "delete":
        return delete(profile, namespace=args.namespace, doc=args.doc)
    if sub == "compile":
        return compile_(profile, namespace=args.namespace,
                        doc_names=args.docs,
                        flags=getattr(args, "flags", "ck"))
    return error_envelope(
        "source",
        code=ErrorCode.USAGE,
        message="source needs a sub-verb: list | get | put | delete | compile",
        hint="example: irisctl source list USER",
    )
