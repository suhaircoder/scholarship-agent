"""Read the public WordPress post API. Title, excerpt, and the deadline lines only."""

from __future__ import annotations

import json
import time
from datetime import datetime

from dateutil import parser as date_parser

from scholarship_agent.classify import schedule_notes
from scholarship_agent.errors import SourceFetchError
from scholarship_agent.http_client import HttpFetcher
from scholarship_agent.models import RawItem
from scholarship_agent.profiles import SourceConfig
from scholarship_agent.textutil import clean_text


def parse_wp_posts(payload: str, source_id: str) -> list[RawItem]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SourceFetchError(source_id, "unreadable post list") from exc
    if not isinstance(data, list):
        return []
    found: list[RawItem] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = clean_text(_rendered(entry.get("title")), limit=400)
        url = str(entry.get("link") or "").strip()
        if len(title) < 8 or not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        published = _published(entry.get("date"))
        excerpt = clean_text(_rendered(entry.get("excerpt")), limit=700)
        article = clean_text(_rendered(entry.get("content")), limit=50000)
        notes = schedule_notes(article or excerpt)
        found.append(
            RawItem(
                source_id=source_id,
                title=title,
                url=url,
                summary=clean_text(f"{notes} {excerpt}".strip(), limit=1200),
                published_at=published,
            )
        )
    return found


def _rendered(value) -> str:
    if isinstance(value, dict):
        value = value.get("rendered") or ""
    return str(value or "")


def _published(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    return parsed


class WordPressPostScraper:
    def __init__(self, fetcher: HttpFetcher, delay_seconds: float, sleep=time.sleep) -> None:
        self._fetcher = fetcher
        self._delay = delay_seconds
        self._sleep = sleep

    def fetch(self, source: SourceConfig, *, conditional: bool = True) -> list[RawItem]:
        items: list[RawItem] = []
        seen: set[str] = set()
        for page in range(source.pages):
            if page:
                self._pause()
            url = source.url if page == 0 else _with_page(source.url, page + 1)
            try:
                result = self._fetcher.get_text(url, conditional=conditional and page == 0)
            except SourceFetchError as exc:
                if page and items:
                    break
                raise SourceFetchError(source.id, str(exc)) from exc
            if result.not_modified:
                return []
            for item in parse_wp_posts(result.text, source.id):
                if item.url not in seen:
                    seen.add(item.url)
                    items.append(item)
            if page and not result.text.strip():
                break
        return items

    def _pause(self) -> None:
        if self._delay > 0:
            self._sleep(self._delay)


def _with_page(url: str, page: int) -> str:
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}page={page}"
