"""The runner's API client. Outbound calls only."""

from __future__ import annotations

import time
from typing import Any

import httpx

from . import __version__


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class Api:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {"User-Agent": f"lintel-runner/{__version__}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)

    def _call(self, method: str, path: str, *, retries: int = 3, **kw: Any) -> Any:
        delay = 0.5
        for attempt in range(retries + 1):
            try:
                r = self.http.request(method, path, **kw)
            except httpx.TransportError:
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 204:
                return None
            if r.status_code >= 400:
                try:
                    err = r.json().get("error", {})
                except ValueError:
                    err = {}
                raise ApiError(r.status_code, err.get("code", "error"), err.get("message", r.text[:200]))
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
            return r.content
        return None

    def get(self, path: str, **kw: Any) -> Any:
        return self._call("GET", path, **kw)

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        return self._call("POST", path, json=json, **kw)

    def post_once(self, path: str, json: Any = None) -> Any:
        """For the submit intent: never retried blindly, because a lost reply is not a lost write."""

        return self._call("POST", path, json=json, retries=0)
