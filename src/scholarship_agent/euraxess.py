"""Read the public EURAXESS search pages. One page is only about ten jobs."""

from __future__ import annotations

import html
import re
import time

from scholarship_agent.errors import SourceFetchError
from scholarship_agent.http_client import HttpFetcher
from scholarship_agent.models import RawItem
from scholarship_agent.profiles import SourceConfig
from scholarship_agent.textutil import clean_text

_LINK = re.compile(r'href="([^"]*/jobs/\d+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_ARTICLE = re.compile(r'<article class="ecl-content-item">(.*?)</article>', re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SKIP = {"apply", "read more", "more", "share"}


def parse_euraxess_listings(page: str, source_id: str) -> list[RawItem]:
    articles = _ARTICLE.findall(page)
    if articles:
        return _from_blocks(articles, source_id)
    return _from_links(page, source_id, summary_from_title=True)


def _from_blocks(articles: list[str], source_id: str) -> list[RawItem]:
    found: list[RawItem] = []
    seen: set[str] = set()
    for article in articles:
        for item in _from_links(article, source_id, summary_from_title=False):
            if item.url in seen:
                continue
            seen.add(item.url)
            summary = clean_text(article, limit=1500)
            found.append(item.model_copy(update={"summary": summary or item.title}))
    return found


def _from_links(page: str, source_id: str, *, summary_from_title: bool) -> list[RawItem]:
    found: list[RawItem] = []
    seen: set[str] = set()
    for href, raw_title in _LINK.findall(page):
        title = " ".join(_TAG.sub(" ", html.unescape(raw_title)).split())
        if len(title) < 8 or title.lower() in _SKIP:
            continue
        url = href if href.startswith("http") else f"https://euraxess.ec.europa.eu{href}"
        url = url.split("?")[0].rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        found.append(RawItem(source_id=source_id, title=title, url=url, summary=title if summary_from_title else title))
    return found


class EuraxessSearchScraper:
    def __init__(self, fetcher: HttpFetcher, delay_seconds: float, sleep=time.sleep) -> None:
        self._fetcher = fetcher
        self._delay = delay_seconds
        self._sleep = sleep

    def fetch(self, source: SourceConfig, *, conditional: bool = True) -> list[RawItem]:
        del conditional
        items: list[RawItem] = []
        seen: set[str] = set()
        for page in range(source.pages):
            if page:
                self._pause()
            url = source.url if page == 0 else f"{source.url}?page={page}"
            try:
                result = self._fetcher.get_text(url, conditional=False)
            except SourceFetchError as exc:
                raise SourceFetchError(source.id, str(exc)) from exc
            for item in parse_euraxess_listings(result.text, source.id):
                if item.url not in seen:
                    seen.add(item.url)
                    items.append(item)
        return items

    def _pause(self) -> None:
        if self._delay > 0:
            self._sleep(self._delay)
