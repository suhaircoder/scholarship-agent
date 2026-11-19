"""Read public RSS and Atom feeds into raw listings."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import feedparser

from scholarship_agent.classify import schedule_notes
from scholarship_agent.errors import SourceFetchError
from scholarship_agent.http_client import HttpFetcher
from scholarship_agent.models import RawItem
from scholarship_agent.profiles import SourceConfig
from scholarship_agent.textutil import clean_text

logger = logging.getLogger(__name__)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_rss(payload: str, source_id: str, max_items: int) -> list[RawItem]:
    parsed = feedparser.parse(payload)
    entries = list(parsed.entries)
    if getattr(parsed, "bozo", False) and not entries:
        reason = getattr(parsed, "bozo_exception", "unreadable feed")
        raise SourceFetchError(source_id, f"unreadable feed: {reason}")
    items: list[RawItem] = []
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        if not title or not link:
            continue
        categories: list[str] = []
        for tag in entry.get("tags", []):
            term = tag.get("term") if isinstance(tag, dict) else getattr(tag, "term", "")
            if term:
                categories.append(str(term))
        excerpt = str(entry.get("summary") or entry.get("description") or "")
        article = _article_body(entry)
        notes = schedule_notes(clean_text(article or excerpt, limit=50000))
        items.append(
            RawItem(
                source_id=source_id,
                title=title,
                url=link,
                summary=clean_text(f"{notes} {excerpt}".strip(), limit=1200),
                organization=str(entry.get("author") or ""),
                published_at=_published(entry),
                categories=categories,
            )
        )
    items.sort(key=lambda item: item.published_at or _EPOCH, reverse=True)
    if max_items > 0:
        return items[:max_items]
    return items


def _article_body(entry: dict) -> str:
    content = entry.get("content")
    if not isinstance(content, list) or not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return str(first.get("value") or "")
    return str(getattr(first, "value", "") or "")


def _published(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        year = int(parsed[0])
        if year < 100:
            year += 2000
        return datetime(year, parsed[1], parsed[2], parsed[3], parsed[4], parsed[5], tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


class RssScraper:
    def __init__(self, fetcher: HttpFetcher, max_items: int) -> None:
        self._fetcher = fetcher
        self._max_items = max_items

    def fetch(self, source: SourceConfig, *, conditional: bool = True) -> list[RawItem]:
        try:
            result = self._fetcher.get_text(source.url, conditional=conditional)
        except SourceFetchError as exc:
            raise SourceFetchError(source.id, str(exc)) from exc
        if result.not_modified:
            logger.info("%s has not changed since the last read", source.id)
            return []
        return parse_rss(result.text, source.id, self._max_items)


class ScraperRegistry:
    """Pause between sources so a run stays a reader, not a crawler."""

    def __init__(self, scraper: RssScraper, delay_seconds: float, sleep=time.sleep, euraxess=None, wordpress=None) -> None:
        self._scraper = scraper
        self._euraxess = euraxess
        self._wordpress = wordpress
        self._delay = delay_seconds
        self._sleep = sleep
        self._last_fetch = 0.0

    def fetch(self, source: SourceConfig, *, conditional: bool = True) -> list[RawItem]:
        if source.type not in {"rss", "euraxess_search", "wp_posts"}:
            raise SourceFetchError(source.id, f"unsupported source type '{source.type}'")
        self._wait()
        try:
            if source.type == "euraxess_search":
                if self._euraxess is None:
                    raise SourceFetchError(source.id, "EURAXESS search is not configured")
                return self._euraxess.fetch(source)
            if source.type == "wp_posts":
                if self._wordpress is None:
                    raise SourceFetchError(source.id, "WordPress posts are not configured")
                return self._wordpress.fetch(source, conditional=conditional)
            return self._scraper.fetch(source, conditional=conditional)
        finally:
            self._last_fetch = time.monotonic()

    def _wait(self) -> None:
        if self._delay <= 0 or self._last_fetch == 0:
            return
        elapsed = time.monotonic() - self._last_fetch
        remaining = self._delay - elapsed
        if remaining > 0:
            self._sleep(remaining)
