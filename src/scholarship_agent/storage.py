"""SQLite memory for listings, matches, feed validators, and run history."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from scholarship_agent.models import Opportunity, PendingMatch

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    organization TEXT NOT NULL,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    degree_levels TEXT NOT NULL,
    opportunity_types TEXT NOT NULL,
    countries TEXT NOT NULL,
    fields TEXT NOT NULL,
    funding TEXT NOT NULL,
    deadline TEXT,
    confidence REAL NOT NULL,
    is_actionable INTEGER NOT NULL,
    ai_summary TEXT NOT NULL,
    match_text TEXT NOT NULL,
    title_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    duplicate_of TEXT,
    enriched INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    score REAL NOT NULL,
    reasons TEXT NOT NULL,
    status TEXT NOT NULL,
    reject_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(opportunity_id, profile_id),
    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);

CREATE TABLE IF NOT EXISTS channel_deliveries (
    match_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    attempted_at TEXT NOT NULL,
    PRIMARY KEY (match_id, channel),
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS feed_validators (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    sources_ok INTEGER NOT NULL,
    sources_failed INTEGER NOT NULL,
    fetched INTEGER NOT NULL,
    changed INTEGER NOT NULL,
    delivered INTEGER NOT NULL,
    errors TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio (
    opportunity_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);

CREATE INDEX IF NOT EXISTS idx_opportunities_title_key ON opportunities(title_key);
CREATE INDEX IF NOT EXISTS idx_matches_profile_status ON matches(profile_id, status);
"""


def _dump(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _load_list(value: str) -> list[str]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


class Repository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def get_validators(self, url: str) -> tuple[str | None, str | None]:
        row = self.conn.execute(
            "SELECT etag, last_modified FROM feed_validators WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None, None
        return row["etag"], row["last_modified"]

    def save_validators(self, url: str, etag: str | None, last_modified: str | None) -> None:
        self.conn.execute(
            """
            INSERT INTO feed_validators (url, etag, last_modified)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, last_modified = excluded.last_modified
            """,
            (url, etag, last_modified),
        )

    def get_by_url(self, url: str) -> Opportunity | None:
        row = self.conn.execute("SELECT * FROM opportunities WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        return self._opportunity(row)

    def find_canonical_url(self, title_key: str, url: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT url FROM opportunities
            WHERE title_key = ? AND url != ? AND duplicate_of IS NULL
            ORDER BY fetched_at ASC
            LIMIT 1
            """,
            (title_key, url),
        ).fetchone()
        if row is None:
            return None
        return str(row["url"])

    def upsert_opportunity(self, opportunity: Opportunity) -> tuple[Opportunity, bool]:
        existing = self.get_by_url(opportunity.url)
        if existing and existing.content_hash == opportunity.content_hash:
            unchanged = (
                list(existing.degree_levels) == list(opportunity.degree_levels)
                and list(existing.opportunity_types) == list(opportunity.opportunity_types)
                and existing.is_actionable == opportunity.is_actionable
                and list(existing.countries) == list(opportunity.countries)
                and existing.funding == opportunity.funding
                and existing.deadline == opportunity.deadline
            )
            if unchanged:
                return existing, False
        packed = (
            opportunity.title,
            opportunity.summary,
            opportunity.organization,
            _iso(opportunity.published_at),
            _dump(opportunity.degree_levels),
            _dump(opportunity.opportunity_types),
            _dump(opportunity.countries),
            _dump(opportunity.fields),
            opportunity.funding,
            opportunity.deadline.isoformat() if opportunity.deadline else None,
            opportunity.confidence,
            int(opportunity.is_actionable),
            opportunity.ai_summary,
            opportunity.match_text,
            opportunity.title_key,
            opportunity.content_hash,
            int(opportunity.enriched),
        )
        if existing:
            self.conn.execute(
                """
                UPDATE opportunities SET
                    title = ?, summary = ?, organization = ?, published_at = ?,
                    degree_levels = ?, opportunity_types = ?, countries = ?, fields = ?,
                    funding = ?, deadline = ?, confidence = ?, is_actionable = ?,
                    ai_summary = ?, match_text = ?, title_key = ?, content_hash = ?,
                    enriched = ?
                WHERE id = ?
                """,
                (*packed, existing.id),
            )
            stored = self.get_by_url(opportunity.url)
            assert stored is not None
            return stored, True
        self.conn.execute(
            """
            INSERT INTO opportunities (
                id, source_id, url, fetched_at, duplicate_of,
                title, summary, organization, published_at,
                degree_levels, opportunity_types, countries, fields,
                funding, deadline, confidence, is_actionable,
                ai_summary, match_text, title_key, content_hash, enriched
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity.id,
                opportunity.source_id,
                opportunity.url,
                _iso(opportunity.fetched_at),
                opportunity.duplicate_of,
                *packed,
            ),
        )
        return opportunity, True

    def upsert_match(
        self,
        opportunity_id: str,
        profile_id: str,
        score: float,
        reasons: list[str],
        accepted: bool,
        reject_reason: str | None,
        now: datetime,
    ) -> int | None:
        row = self.conn.execute(
            "SELECT id, status FROM matches WHERE opportunity_id = ? AND profile_id = ?",
            (opportunity_id, profile_id),
        ).fetchone()
        if row is not None and row["status"] == "sent":
            return None
        status = "pending" if accepted else "rejected"
        stamp = now.isoformat()
        payload = (score, _dump(reasons), status, reject_reason, stamp)
        if row is None:
            if not accepted:
                return None
            cursor = self.conn.execute(
                """
                INSERT INTO matches (
                    opportunity_id, profile_id, score, reasons, status, reject_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (opportunity_id, profile_id, *payload, stamp),
            )
            return int(cursor.lastrowid)
        self.conn.execute(
            """
            UPDATE matches
            SET score = ?, reasons = ?, status = ?, reject_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (*payload, row["id"]),
        )
        return int(row["id"]) if accepted else None

    def count_by_source(self, source_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM opportunities WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return int(row["total"])

    def get_by_id(self, opportunity_id: str) -> Opportunity | None:
        row = self.conn.execute(
            "SELECT * FROM opportunities WHERE id = ?",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return None
        return self._opportunity(row)

    def save_to_portfolio(self, opportunity_id: str, now: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO portfolio (opportunity_id, status, saved_at)
            VALUES (?, 'saved', ?)
            ON CONFLICT(opportunity_id) DO NOTHING
            """,
            (opportunity_id, now.isoformat()),
        )

    def set_portfolio_status(self, opportunity_id: str, status: str) -> None:
        if status not in {"saved", "applying", "applied"}:
            return
        self.conn.execute(
            "UPDATE portfolio SET status = ? WHERE opportunity_id = ?",
            (status, opportunity_id),
        )

    def remove_from_portfolio(self, opportunity_id: str) -> None:
        self.conn.execute("DELETE FROM portfolio WHERE opportunity_id = ?", (opportunity_id,))

    def list_portfolio(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT opportunity_id, status FROM portfolio ORDER BY saved_at DESC"
        )
        return [(str(row["opportunity_id"]), str(row["status"])) for row in rows]

    def list_opportunities(self) -> list[Opportunity]:
        rows = self.conn.execute(
            """
            SELECT * FROM opportunities
            WHERE duplicate_of IS NULL
            ORDER BY published_at DESC
            """
        )
        return [self._opportunity(row) for row in rows]

    def pending_matches(self, profile_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT m.id AS match_id, m.score, m.reasons, o.*
                FROM matches m
                JOIN opportunities o ON o.id = m.opportunity_id
                WHERE m.profile_id = ? AND m.status = 'pending'
                ORDER BY m.score DESC, o.published_at DESC
                """,
                (profile_id,),
            )
        )

    def pending_for(self, profile_id: str) -> list[PendingMatch]:
        return self.matches_for(profile_id, statuses=("pending",))

    def matches_for(self, profile_id: str, statuses: tuple[str, ...] = ("pending", "sent")) -> list[PendingMatch]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"""
            SELECT m.id AS match_id, m.score, m.reasons, m.status, o.*
            FROM matches m
            JOIN opportunities o ON o.id = m.opportunity_id
            WHERE m.profile_id = ? AND m.status IN ({placeholders})
            ORDER BY m.score DESC, o.published_at DESC
            """,
            (profile_id, *statuses),
        )
        return [
            PendingMatch(
                match_id=int(row["match_id"]),
                score=float(row["score"]),
                reasons=_load_list(row["reasons"]),
                opportunity=self._opportunity(row),
                status=str(row["status"]),
            )
            for row in rows
        ]

    def record_delivery(self, match_id: int, channel: str, status: str, detail: str, now: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO channel_deliveries (match_id, channel, status, detail, attempted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(match_id, channel) DO UPDATE SET
                status = excluded.status,
                detail = excluded.detail,
                attempted_at = excluded.attempted_at
            """,
            (match_id, channel, status, detail[:300], now.isoformat()),
        )

    def successful_channels(self, match_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT channel FROM channel_deliveries WHERE match_id = ? AND status = 'sent'",
            (match_id,),
        )
        return {str(row["channel"]) for row in rows}

    def mark_sent(self, match_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE matches SET status = 'sent', updated_at = ? WHERE id = ?",
            (now.isoformat(), match_id),
        )

    def add_run(self, **fields: object) -> None:
        self.conn.execute(
            """
            INSERT INTO runs (
                started_at, finished_at, dry_run, sources_ok, sources_failed,
                fetched, changed, delivered, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["started_at"],
                fields["finished_at"],
                int(bool(fields["dry_run"])),
                fields["sources_ok"],
                fields["sources_failed"],
                fields["fetched"],
                fields["changed"],
                fields["delivered"],
                fields["errors"],
            ),
        )

    def _opportunity(self, row: sqlite3.Row) -> Opportunity:
        published = row["published_at"]
        deadline = row["deadline"]
        duplicate = row["duplicate_of"]
        return Opportunity(
            id=row["id"],
            source_id=row["source_id"],
            title=row["title"],
            url=row["url"],
            summary=row["summary"],
            organization=row["organization"],
            published_at=datetime.fromisoformat(published) if published else None,
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            degree_levels=_load_list(row["degree_levels"]),
            opportunity_types=_load_list(row["opportunity_types"]),
            countries=_load_list(row["countries"]),
            fields=_load_list(row["fields"]),
            funding=row["funding"],
            deadline=date.fromisoformat(deadline) if deadline else None,
            confidence=row["confidence"],
            is_actionable=bool(row["is_actionable"]),
            ai_summary=row["ai_summary"],
            match_text=row["match_text"],
            title_key=row["title_key"],
            content_hash=row["content_hash"],
            duplicate_of=duplicate,
            enriched=bool(row["enriched"]),
        )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
