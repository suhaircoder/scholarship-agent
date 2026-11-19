"""Polite HTTP reads with retries and conditional requests."""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from scholarship_agent.errors import SourceFetchError

_RETRY_STATUSES = {429, 500, 502, 503, 504}


class FeedCache(Protocol):
    def get_validators(self, url: str) -> tuple[str | None, str | None]:
        """Return the stored ETag and Last-Modified value for a feed URL."""

    def save_validators(self, url: str, etag: str | None, last_modified: str | None) -> None:
        """Remember validators so the next run can send a conditional request."""


@dataclass
class FetchResult:
    not_modified: bool = False
    text: str = ""


def normalize_proxy(url: str | None) -> str | None:
    """Turn the OS proxy into a URL httpx can use.

    Windows often exposes a local SOCKS4 proxy. httpx speaks SOCKS5, and the
    local forwarder on that port accepts SOCKS5 as well.
    """
    if not url:
        return None
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in {"socks4", "socks4a", "socks", "socks5"}:
        scheme = "socks5h"
    elif scheme not in {"http", "https", "socks5h"}:
        return None
    if not parts.netloc:
        return None
    return urlunsplit((scheme, parts.netloc, "", "", ""))


def _system_proxy() -> str | None:
    proxies = urllib.request.getproxies()
    raw = proxies.get("https") or proxies.get("http") or proxies.get("socks")
    return normalize_proxy(raw)


class MemoryFeedCache:
    """Process-local cache used in tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str | None, str | None]] = {}

    def get_validators(self, url: str) -> tuple[str | None, str | None]:
        return self._data.get(url, (None, None))

    def save_validators(self, url: str, etag: str | None, last_modified: str | None) -> None:
        self._data[url] = (etag, last_modified)


class HttpFetcher:
    def __init__(
        self,
        *,
        cache: FeedCache,
        timeout: float,
        max_retries: int,
        user_agent: str,
        client: httpx.Client | None = None,
        sleep=time.sleep,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._cache = cache
        self._retries = max(1, max_retries)
        self._sleep = sleep
        self._backoff = backoff_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            trust_env=False,
            proxy=_system_proxy(),
            headers={
                "User-Agent": user_agent,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_text(self, url: str, *, conditional: bool = True) -> FetchResult:
        headers: dict[str, str] = {}
        if conditional:
            etag, modified = self._cache.get_validators(url)
            if etag:
                headers["If-None-Match"] = etag
            if modified:
                headers["If-Modified-Since"] = modified
        response = self._request(url, headers)
        if response.status_code == 304:
            return FetchResult(not_modified=True)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SourceFetchError("http", f"{url} returned {response.status_code}") from exc
        self._cache.save_validators(
            url,
            response.headers.get("ETag"),
            response.headers.get("Last-Modified"),
        )
        return FetchResult(text=response.text)

    def _request(self, url: str, headers: dict[str, str]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                response = self._client.get(url, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._retries:
                    break
                self._sleep(self._backoff * attempt)
                continue
            if response.status_code in _RETRY_STATUSES and attempt < self._retries:
                self._sleep(self._backoff * attempt)
                continue
            return response
        raise SourceFetchError("http", f"failed to fetch {url}: {last_error}")
