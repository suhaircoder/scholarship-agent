"""Shared records for listings, people, and delivery."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RawItem(BaseModel):
    """One entry taken from a feed, before classification."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    title: str
    url: str
    summary: str = ""
    organization: str = ""
    published_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)


class Opportunity(BaseModel):
    """A normalized listing stored and compared with user profiles."""

    id: str
    source_id: str
    title: str
    url: str
    summary: str = ""
    organization: str = ""
    published_at: datetime | None = None
    fetched_at: datetime
    degree_levels: list[str] = Field(default_factory=list)
    opportunity_types: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    funding: str = "unknown"
    deadline: date | None = None
    confidence: float = 0.0
    is_actionable: bool = True
    ai_summary: str = ""
    match_text: str = ""
    title_key: str = ""
    content_hash: str = ""
    duplicate_of: str | None = None
    enriched: bool = False


class ScoreDecision(BaseModel):
    """Why a listing was kept or dropped for one person."""

    accepted: bool
    score: float
    reasons: list[str] = Field(default_factory=list)
    reject_reason: str | None = None


class DigestItem(BaseModel):
    match_id: int
    title: str
    url: str
    source_id: str
    organization: str = ""
    summary: str = ""
    score: float
    reasons: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    funding: str = "unknown"
    deadline: date | None = None
    published_at: datetime | None = None


class PendingMatch(BaseModel):
    match_id: int
    score: float
    reasons: list[str] = Field(default_factory=list)
    opportunity: Opportunity
    status: str = "pending"


class Digest(BaseModel):
    profile_id: str
    display_name: str
    generated_at: datetime
    items: list[DigestItem]
    channel: str = ""
