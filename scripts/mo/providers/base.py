from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..models import EpisodeRef, MovieRef, SeriesRef
from ..state import State

USER_AGENT = "media-organizer/0.1 (+local lab tool)"
DEFAULT_TIMEOUT = 25
TTL_SEARCH = 7 * 86400
TTL_DETAIL = 30 * 86400
TTL_SUBTITLE = 7 * 86400


class ProviderError(RuntimeError):
    pass


def _redact(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe = [(k, "***" if k.lower() in {"api_key", "apikey", "key", "token"} else v) for k, v in q]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe), ""))


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]


class CacheStore:
    def __init__(self, state: State):
        self.conn = state.conn

    def get(self, key: str, ttl: int) -> Any | None:
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM provider_cache WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return None
        if ttl >= 0 and time.time() - row["fetched_at"] > ttl:
            return None
        try:
            return json.loads(row["payload"])
        except Exception:
            return None

    def get_etag(self, key: str) -> str | None:
        row = self.conn.execute("SELECT etag FROM provider_cache WHERE key=?", (key,)).fetchone()
        return row["etag"] if row else None

    def put(self, key: str, payload: Any, etag: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO provider_cache(key,fetched_at,etag,payload) VALUES(?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at,
               etag=excluded.etag,payload=excluded.payload""",
            (key, time.time(), etag, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()


class HttpClient:
    def __init__(self, state: State, min_interval: float = 0.25):
        self.cache = CacheStore(state)
        self.min_interval = min_interval
        self._last: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        now = time.monotonic()
        last = self._last.get(host, 0.0)
        wait = self.min_interval - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def _open(self, req: urllib.request.Request) -> HttpResponse:
        host = urllib.parse.urlsplit(req.full_url).netloc
        self._throttle(host)
        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                body = resp.read()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                if headers.get("content-encoding") == "gzip" or req.full_url.endswith(".gz"):
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return HttpResponse(resp.status, body, headers)
        except urllib.error.HTTPError as e:
            body = e.read()
            return HttpResponse(e.code, body, {k.lower(): v for k, v in e.headers.items()})
        except urllib.error.URLError as e:
            raise ProviderError(f"network error: {e.reason}") from e

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any | None = None,
        ttl: int = TTL_DETAIL,
        cache_key: str | None = None,
        retries: int = 2,
    ) -> HttpResponse:
        if params:
            pairs = []
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, (list, tuple)):
                    for item in v:
                        pairs.append((k, item))
                else:
                    pairs.append((k, v))
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(pairs)
        key = cache_key or hashlib.sha256(
            (method + "\n" + url).encode("utf-8")
        ).hexdigest()
        if method.upper() == "GET" and ttl >= 0:
            cached = self.cache.get(key, ttl)
            if cached is not None:
                return HttpResponse(200, json.dumps(cached).encode("utf-8"), {"x-cache": "hit"})

        hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif method.upper() in {"POST", "PUT", "PATCH"}:
            body = b""

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
            try:
                resp = self._open(req)
            except ProviderError as e:
                last_error = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            if resp.status in (200, 201, 203):
                if method.upper() == "GET" and ttl >= 0:
                    try:
                        self.cache.put(key, json.loads(resp.body.decode("utf-8")))
                    except Exception:
                        pass
                return resp
            if resp.status == 304:
                cached = self.cache.get(key, -1)
                if cached is not None:
                    return HttpResponse(200, json.dumps(cached).encode("utf-8"), {"x-cache": "304"})
            if resp.status == 429 or 500 <= resp.status < 600:
                last_error = ProviderError(f"HTTP {resp.status} for {_redact(url)}")
                if attempt < retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise last_error
            if resp.status in (401, 403):
                raise ProviderError(f"HTTP {resp.status}: authentication/permission error ({_redact(url)})")
            if resp.status == 404:
                return resp
            snippet = resp.body[:200].decode("utf-8", "replace")
            raise ProviderError(f"HTTP {resp.status} for {_redact(url)}: {snippet}")
        raise last_error or ProviderError("request failed")

    def get_json(self, url: str, params=None, headers=None, ttl=TTL_DETAIL) -> Any:
        resp = self.request("GET", url, params=params, headers=headers, ttl=ttl)
        if resp.status == 404:
            return None
        try:
            return json.loads(resp.body.decode("utf-8"))
        except Exception as e:
            raise ProviderError(f"invalid JSON from {_redact(url)}: {e}") from e

    def post_json(self, url: str, data: Any, headers=None, ttl=-1) -> Any:
        resp = self.request("POST", url, headers=headers, data=data, ttl=ttl)
        try:
            return json.loads(resp.body.decode("utf-8"))
        except Exception as e:
            raise ProviderError(f"invalid JSON from {_redact(url)}: {e}") from e

    def get_bytes(self, url: str, headers=None) -> bytes:
        resp = self.request("GET", url, headers=headers, ttl=-1)
        if resp.status != 200:
            raise ProviderError(f"HTTP {resp.status} downloading {_redact(url)}")
        return resp.body


class Provider:
    name = "base"

    def __init__(self, state: State, index=None):
        self.state = state
        self.index = index
        self.http = HttpClient(state)

    def search_series(self, query: str, year: int | None = None) -> list[SeriesRef]:
        return []

    def episodes(self, series_id: str) -> list[EpisodeRef]:
        return []

    def search_movies(self, query: str, year: int | None = None) -> list[MovieRef]:
        return []

    def require_key(self, env: str, label: str) -> str:
        key = os.environ.get(env) or (self.state.config.get("keys", {}) or {}).get(label)
        if not key:
            raise ProviderError(
                f"{label} API key is not configured; set {env} or add keys.{label} to config.json"
            )
        return str(key)
