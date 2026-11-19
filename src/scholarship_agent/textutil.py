"""Text cleanup and stable identity for listings."""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG = re.compile(r"(?is)<(script|style).*?>.*?</\1>|<[^>]+>")
_SPACE = re.compile(r"\s+")
_YEAR = re.compile(r"20\d{2}")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def clean_text(value: str, limit: int = 1200) -> str:
    """Drop markup and collapse whitespace. Keep the RSS excerpt, not a full article."""
    text = value.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _SPACE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def title_key(title: str) -> str:
    text = clean_text(title, limit=500).lower()
    text = _YEAR.sub(" ", text)
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def is_distinctive_title(key: str) -> bool:
    """Short titles such as 'Assistant Professor' are shared by unrelated jobs."""
    return len(key) >= 60 and len(key.split()) >= 8


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def content_hash(title: str, summary: str) -> str:
    payload = f"{title}\n{summary}".encode()
    return hashlib.sha256(payload).hexdigest()


def opportunity_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def term_in_text(term: str, text: str) -> bool:
    if not term.strip():
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None
