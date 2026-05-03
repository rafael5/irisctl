"""Atelier source-code REST client.

Wraps `/api/atelier/v{N}/` for source-code CRUD. The version segment
is auto-probed (v6 → v1) since the lowest supported version varies by
IRIS build. Probe accepts 200 or 401 as proof-of-existence — we don't
need credentials to discover the version.

Endpoints exposed:
    GET    /api/atelier/v{N}/                                 GetServer
    GET    /api/atelier/v{N}/{namespace}/docnames             list docs
    GET    /api/atelier/v{N}/{namespace}/doc/{docname}        read doc
    PUT    /api/atelier/v{N}/{namespace}/doc/{docname}        write doc
    DELETE /api/atelier/v{N}/{namespace}/doc/{docname}        remove doc
    POST   /api/atelier/v{N}/{namespace}/action/compile       compile
"""

from __future__ import annotations

from typing import Any

import httpx

from irisctl.http_api import AuthRequired, NetworkError

ATELIER_VERSIONS = ("v6", "v5", "v4", "v3", "v2", "v1")


def probe_version(
    base_url: str,
    timeout: float = 3.0,
) -> str:
    """Find the highest-supported Atelier API version.

    Returns the version segment string (e.g. "v6"). 401 counts as
    "version exists, auth required"; the probe doesn't need creds.
    Raises NetworkError if the host is unreachable; KeyError if no
    version responds at all (would indicate a non-IRIS server).
    """
    last_err: Exception | None = None
    for v in ATELIER_VERSIONS:
        url = f"{base_url.rstrip('/')}/api/atelier/{v}/"
        try:
            r = httpx.get(url, timeout=timeout)
        except httpx.RequestError as e:
            last_err = e
            continue
        if r.status_code in (200, 401):
            return v
    if last_err:
        raise NetworkError(f"{base_url}: {last_err}")
    raise KeyError("no Atelier version responded")


def lines_to_put_payload(lines: list[str]) -> dict[str, Any]:
    """Shape the request body for PutDoc."""
    return {"enc": False, "content": lines}


def parse_get_doc(body: dict[str, Any]) -> dict[str, Any]:
    """Pluck the source-code body out of a GetDoc response.

    Some builds wrap the document under `result`; others put it at the
    top level. Handles both.
    """
    if "result" in body and isinstance(body["result"], dict):
        result = body["result"]
        return {
            "name": result.get("name", ""),
            "content": result.get("content", []),
            "status": result.get("status"),
            "ts": result.get("ts"),
        }
    return {
        "name": body.get("name", ""),
        "content": body.get("content", []),
        "status": body.get("status"),
        "ts": body.get("ts"),
    }


class AtelierClient:
    """HTTP client for /api/atelier/v{N}/."""

    def __init__(
        self,
        base_url: str = "http://localhost:52773",
        auth: tuple[str, str] | None = None,
        timeout: float = 10.0,
        version: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self._version = version

    @property
    def version(self) -> str:
        if self._version is None:
            self._version = probe_version(self.base_url, timeout=self.timeout)
        return self._version

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/atelier/{self.version}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
    ) -> Any:
        url = self._url(path)
        try:
            r = httpx.request(
                method, url,
                auth=self.auth,
                timeout=self.timeout,
                json=json,
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as e:
            raise NetworkError(f"{url}: {e}") from e
        if r.status_code == 401:
            raise AuthRequired(f"{url}: 401")
        r.raise_for_status()
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}

    # -------- public API --------

    def get_server(self) -> dict[str, Any]:
        body = self._request("GET", "/")
        if "result" in body and isinstance(body["result"], dict):
            return body["result"]
        return body

    def get_doc_names(
        self,
        namespace: str,
        *,
        type_: str | None = None,
        filter_: str | None = None,
    ) -> list[dict[str, Any]]:
        path = f"/{namespace}/docnames"
        params: list[str] = []
        if type_:
            params.append(f"type={type_}")
        if filter_:
            params.append(f"filter={filter_}")
        if params:
            path = f"{path}?{'&'.join(params)}"
        body = self._request("GET", path)
        result = body.get("result", body)
        if isinstance(result, dict) and "content" in result:
            return list(result["content"])
        if isinstance(result, list):
            return result
        return []

    def get_doc(self, namespace: str, doc: str) -> dict[str, Any]:
        body = self._request("GET", f"/{namespace}/doc/{doc}")
        return parse_get_doc(body)

    def put_doc(
        self,
        namespace: str,
        doc: str,
        content_lines: list[str],
    ) -> dict[str, Any]:
        body = self._request(
            "PUT", f"/{namespace}/doc/{doc}",
            json=lines_to_put_payload(content_lines),
        )
        return body

    def delete_doc(self, namespace: str, doc: str) -> dict[str, Any]:
        return self._request("DELETE", f"/{namespace}/doc/{doc}")

    def compile_docs(
        self,
        namespace: str,
        doc_names: list[str],
        *,
        flags: str = "ck",
    ) -> dict[str, Any]:
        # Action endpoints accept a list of doc objects or doc names.
        # We send the list-of-names form, which works on v3+.
        payload = [{"name": n} for n in doc_names]
        return self._request(
            "POST", f"/{namespace}/action/compile?flags={flags}",
            json=payload,
        )
