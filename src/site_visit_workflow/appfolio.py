"""AppFolio Database API v0 client — the ONLY AppFolio boundary (ADR 0015).

Ported from `_dev/warehouse/scripts/afv0.py` (the company v0 client), trimmed to
what work orders need. Request shapes, limits and error ladder are recorded in
`docs/research/appfolio/v0-work-orders.md`.

Credentials come from the environment only — AF_V0_CLIENT_ID,
AF_V0_CLIENT_SECRET, AF_V0_DEVELOPER_ID — which Cloud Run injects from Secret
Manager. There is no secrets-file fallback here: nothing secret lives in the repo.

Write rules (from the docs' `_WRITE_NOTES.md`):
- POST carries an Idempotency-Key; transport failure on a write is never
  retried blind — it raises AmbiguousWriteError and the caller reads back.
- 401/403/701 stop the run; 404/400/422 are never retried; 429/503/533 back off.
- Payloads are built from present keys only; `[]` would CLEAR a collection.

How to update this later
------------------------
Re-pull the v0 docs before adding an endpoint and record it in the research note.
Keep `post` as the only write method; a PATCH needs its own ADR (no idempotency).
"""

from __future__ import annotations

import base64
import collections
import os
import time
import urllib.parse
from typing import Any, Iterator

from .errors import ExternalServiceError, ValidationError

BASE_URL = "https://api.appfolio.com/api/v0"
CRED_VARS = ("AF_V0_CLIENT_ID", "AF_V0_CLIENT_SECRET", "AF_V0_DEVELOPER_ID")

# Deliberately under the documented 8/sec, 256/min, 4096/hr.
MAX_PER_SEC, MAX_PER_MIN, MAX_PER_HOUR = 6, 200, 4000
MAX_PAGES = 500
IDEMPOTENCY_KEY_MAX = 256


class AppFolioAuthError(ExternalServiceError):
    """401/403/701 — a human must fix credentials or permissions. Stop the run."""


class AppFolioRejected(ExternalServiceError):
    """400/404/422 — the request is wrong; retrying the same body cannot help."""

    def __init__(self, message: str, status: int, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class AmbiguousWriteError(ExternalServiceError):
    """A write failed in transport; it MAY have applied. Read back before acting."""


def load_credentials(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    missing = [name for name in CRED_VARS if not (env.get(name) or "").strip()]
    if missing:
        raise ValidationError(
            "AppFolio v0 credentials missing from the environment: " + ", ".join(missing)
            + ". In Cloud Run they come from Secret Manager (docs/DEPLOYMENT.md)."
        )
    return {name: env[name].strip() for name in CRED_VARS}


def mask(value: str) -> str:
    return value[:4] + "…" if len(value) > 8 else "****"


def check_idempotency_key(key: str) -> str:
    if not key or len(key) > IDEMPOTENCY_KEY_MAX or any(not 32 <= ord(c) <= 126 for c in key):
        raise ValidationError(f"Idempotency-Key must be 1-{IDEMPOTENCY_KEY_MAX} printable ASCII chars: {key!r}")
    return key


class RateLimiter:
    """Three-tier sliding window over one deque of call timestamps."""

    def __init__(self, sleep: Any = None, clock: Any = None) -> None:
        self.tiers = ((1.0, MAX_PER_SEC), (60.0, MAX_PER_MIN), (3600.0, MAX_PER_HOUR))
        self.calls: collections.deque[float] = collections.deque()
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic

    def acquire(self) -> None:
        while True:
            now = self._clock()
            while self.calls and now - self.calls[0] > self.tiers[-1][0]:
                self.calls.popleft()
            wait = 0.0
            for window, limit in self.tiers:
                recent = [t for t in self.calls if now - t <= window]
                if len(recent) >= limit:
                    wait = max(wait, window - (now - recent[0]) + 0.01)
            if wait <= 0:
                self.calls.append(now)
                return
            self._sleep(wait)


class AppFolioClient:
    def __init__(self, credentials: dict[str, str], session: Any = None, sleep: Any = None) -> None:
        if session is None:
            import requests

            session = requests.Session()
        basic = base64.b64encode(
            f"{credentials['AF_V0_CLIENT_ID']}:{credentials['AF_V0_CLIENT_SECRET']}".encode()
        ).decode()
        session.headers.update({
            "Authorization": "Basic " + basic,
            "X-AppFolio-Developer-ID": credentials["AF_V0_DEVELOPER_ID"],
            "Content-Type": "application/json",
        })
        self.session = session
        self._sleep = sleep or time.sleep
        self.limiter = RateLimiter(sleep=self._sleep)
        self.call_count = 0

    @staticmethod
    def _path(path: str, filters: dict[str, Any] | None, page_size: int) -> str:
        params = ["page[number]=1", f"page[size]={page_size}"]
        for key, value in (filters or {}).items():
            if value not in (None, ""):
                params.append(f"filters[{key}]={urllib.parse.quote(str(value), safe=',')}")
        return f"{path}?{'&'.join(params)}"

    @staticmethod
    def _absolute(path: str) -> str:
        if path.startswith("http"):
            return path
        if path.startswith("/api/"):
            return "https://api.appfolio.com" + path
        return BASE_URL + path

    def _request(self, method: str, url: str, body: Any = None,
                 headers: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        is_write = method.upper() != "GET"
        attempt = maintenance = 0
        while True:
            self.limiter.acquire()
            self.call_count += 1
            try:
                resp = self.session.request(method, url, timeout=120, json=body, headers=headers)
            except Exception as error:  # noqa: BLE001 - transport layer
                if is_write:
                    raise AmbiguousWriteError(
                        f"{method} {url} failed in transport ({error}); it may have applied. "
                        "Not retried — read back by marker before acting."
                    ) from error
                attempt += 1
                if attempt >= 3:
                    raise ExternalServiceError(f"AppFolio network failure x3 on {url}: {error}") from error
                self._sleep(2 * attempt)
                continue
            code = resp.status_code
            text = resp.text or ""
            if code in (200, 201, 202, 204):
                return (resp.json() if text.strip() else {}), dict(resp.headers)
            if code in (401, 403, 701):
                raise AppFolioAuthError(f"AppFolio auth/permission failure HTTP {code} on {method} {url}: {text[:300]}")
            if code in (400, 404, 422):
                raise AppFolioRejected(f"AppFolio HTTP {code} on {method} {url}: {text[:1000]}", code, text)
            if code == 409:
                attempt += 1
                if attempt >= 2:
                    raise ExternalServiceError(f"AppFolio 409 twice on {method} {url}")
                self._sleep(int(resp.headers.get("Retry-After") or 1))
                continue
            if code == 429:
                self._sleep(int(resp.headers.get("Retry-After") or 5))
                continue
            if code in (500, 503):
                attempt += 1
                if attempt >= 3:
                    raise ExternalServiceError(f"AppFolio {code} x3 on {method} {url}")
                self._sleep(5 * attempt)
                continue
            if code == 533:
                maintenance += 1
                if maintenance > 2:
                    raise ExternalServiceError("AppFolio 533 (maintenance) repeatedly — rerun later.")
                self._sleep(300)
                continue
            raise ExternalServiceError(f"AppFolio HTTP {code} on {method} {url}: {text[:500]}")

    def get(self, path: str, filters: dict[str, Any], page_size: int = 1000) -> Iterator[dict[str, Any]]:
        if not (filters.get("Id") or filters.get("LastUpdatedAtFrom")):
            raise ValidationError("v0 GET requires filters[Id] or filters[LastUpdatedAtFrom].")
        next_path: str | None = self._path(path, filters, page_size)
        pages = 0
        while next_path:
            payload, _ = self._request("GET", self._absolute(next_path))
            yield from payload.get("data") or []
            pages += 1
            next_path = payload.get("next_page_path") or None
            if pages >= MAX_PAGES:
                raise ExternalServiceError(f"Page guard hit on {path}")

    def get_work_order(self, work_order_id: str) -> dict[str, Any] | None:
        rows = list(self.get("/work_orders", {"Id": work_order_id}, page_size=2))
        if len(rows) > 1:
            raise ExternalServiceError(f"filters[Id]={work_order_id} returned {len(rows)} work orders")
        return rows[0] if rows else None

    def work_orders_since(self, iso_from: str) -> list[dict[str, Any]]:
        return list(self.get("/work_orders", {"LastUpdatedAtFrom": iso_from}))

    def create_work_order(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """POST /work_orders -> {"Id", "Link", "replayed"}."""
        payload, headers = self._request(
            "POST", BASE_URL + "/work_orders", body=body,
            headers={"Idempotency-Key": check_idempotency_key(idempotency_key)},
        )
        if not payload.get("Id"):
            raise ExternalServiceError(f"POST /work_orders returned no Id: {payload}")
        replayed = str(headers.get("Idempotent-Replayed", "")).lower() == "true"
        return {"Id": payload["Id"], "Link": payload.get("Link", ""), "replayed": replayed}

    def create_work_order_note(self, work_order_id: str, note: str, idempotency_key: str) -> dict[str, Any]:
        payload, _ = self._request(
            "POST", f"{BASE_URL}/work_orders/{work_order_id}/notes", body={"Body": note},
            headers={"Idempotency-Key": check_idempotency_key(idempotency_key)},
        )
        return payload
