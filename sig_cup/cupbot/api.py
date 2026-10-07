"""Minimal authenticated client grounded in the supplied OpenAPI 1.0.0 spec."""

from collections import deque
from dataclasses import dataclass
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class APIError(RuntimeError):
    def __init__(self, status, payload, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        self.code = error.get("code", "HTTP_ERROR") if isinstance(error, dict) else "HTTP_ERROR"
        super().__init__(f"API {status}: {self.code}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward a bearer credential to any redirect destination.
        return None


class RateBudget:
    def __init__(self, reads=85, writes=20, clock=time.monotonic, sleep=time.sleep):
        self.limits = {"read": reads, "write": writes}
        self.events = {"read": deque(), "write": deque()}
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()

    def acquire(self, method):
        kind = "read" if method in ("GET", "HEAD") else "write"
        events = self.events[kind]
        while True:
            with self.lock:
                now = self.clock()
                while events and now - events[0] >= 61:
                    events.popleft()
                if len(events) < self.limits[kind]:
                    events.append(now)
                    return
                delay = min(1.0, max(0.01, 61 - (now - events[0])))
            self.sleep(delay)


@dataclass
class Response:
    status: int
    data: dict


class API:
    def __init__(self, base="https://sig.thesuper.market/api/v1", key=None,
                 timeout=20, budget=None, transport=None, sleep=time.sleep):
        parsed = urllib.parse.urlparse(base)
        if (parsed.scheme != "https" or parsed.hostname not in
                {"sig.thesuper.market", "www.thesuper.market"} or
                parsed.username or parsed.password or parsed.port not in (None, 443) or
                parsed.path.rstrip("/") != "/api/v1" or parsed.query or parsed.fragment):
            raise ValueError("Use an official HTTPS /api/v1 base URL.")
        self.base = base.rstrip("/")
        self.key = key if key is not None else os.environ.get("SIG_API_KEY", "")
        if not self.key:
            raise ValueError("Set SIG_API_KEY in the host environment; do not put it in config.")
        self.timeout = timeout
        self.budget = budget or RateBudget()
        self.transport = transport or self._http
        self.sleep = sleep
        self.opener = urllib.request.build_opener(NoRedirect())

    def _http(self, method, url, body):
        encoded = None if body is None else json.dumps(body, allow_nan=False).encode()
        req = urllib.request.Request(url, data=encoded, method=method, headers={
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "EvanKniffen-CupResearch/0.1",
        })
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=self.timeout) as result:
                raw = result.read()
                return result.status, json.loads(raw), dict(result.headers)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                payload = {"error": {"code": "NON_JSON_RESPONSE"}}
            return error.code, payload, dict(error.headers)

    def request(self, method, path, params=None, body=None, attempts=3):
        if not path.startswith("/") or "://" in path:
            raise ValueError("API paths must be relative to the official base.")
        if method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/orders"):
            if method == "POST" and path in ("/orders", "/orders/multi-leg", "/orders/batch"):
                if not (body or {}).get("idempotencyKey"):
                    raise ValueError("Every order operation needs a durable idempotencyKey.")
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = self.base + path + ("?" + query if query else "")
        for attempt in range(attempts):
            self.budget.acquire(method)
            try:
                status, payload, headers = self.transport(method, url, body)
            except (OSError, TimeoutError, urllib.error.URLError):
                # A write might have committed. Only the identical idempotent request can retry.
                if method != "GET" and not (body or {}).get("idempotencyKey"):
                    raise
                if attempt + 1 == attempts:
                    raise
                self.sleep(0.25 * 2 ** attempt)
                continue
            if 200 <= status < 300:
                coverage = payload.get("coverage") if isinstance(payload, dict) else None
                if method == "GET" and isinstance(coverage, dict) and coverage.get("complete") is False:
                    status, payload = 503, {"error": {"code": "INCOMPLETE_READ_COVERAGE"}}
                else:
                    return Response(status, payload)
            error = APIError(status, payload, headers)
            transient = (status == 429 or (status == 409 and error.code == "REQUEST_IN_FLIGHT") or
                         (status == 503 and error.code in ("TX_CONFLICT", "SERVICE_UNAVAILABLE", "INCOMPLETE_READ_COVERAGE")))
            if not transient or attempt + 1 == attempts:
                raise error
            retry_after = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
            try:
                delay = max(0, float(retry_after)) if retry_after is not None else None
            except (ValueError, TypeError):
                delay = None
            if delay is None:
                delay = 60 if status == 429 else (5 if status == 409 else 0.25 * 2 ** attempt)
            until = time.monotonic() + delay + random.random() * 0.1
            while time.monotonic() < until:
                self.sleep(min(1, max(0, until - time.monotonic())))
        raise RuntimeError("Unreachable retry state")

    def get(self, path, **params):
        return self.request("GET", path, params=params).data

    def post(self, path, body):
        return self.request("POST", path, body=body).data

    def pages(self, path, field="data", limit=100, **params):
        rows, cursor, seen = [], None, set()
        for _ in range(1000):
            result = self.get(path, limit=limit, cursor=cursor, **params)
            rows.extend(result[field])
            pagination = result.get("pagination", {})
            if not pagination.get("hasMore", False):
                return rows
            cursor = pagination.get("nextCursor")
            if not cursor or cursor in seen:
                raise RuntimeError("Incomplete/cyclic cursor pagination; refusing partial data.")
            seen.add(cursor)
        raise RuntimeError("Pagination exceeded safety bound.")

    def tournaments(self):
        rows, offset = [], 0
        for _ in range(100):
            result = self.get("/tournaments", status="active", limit=100, offset=offset)
            rows.extend(result["data"])
            if not result["pagination"]["hasMore"]:
                return rows
            if not result["data"]:
                raise RuntimeError("Tournament pagination returned an empty unfinished page.")
            offset += len(result["data"])
        raise RuntimeError("Tournament pagination exceeded safety bound.")
