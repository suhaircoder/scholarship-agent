"""Build a stored listing from one feed entry."""

from __future__ import annotations

from datetime import datetime

from scholarship_agent.classify import classify_text
from scholarship_agent.models import Opportunity, RawItem
from scholarship_agent.textutil import canonical_url, clean_text, content_hash, opportunity_id, title_key


def prepare_opportunity(item: RawItem, now: datetime) -> Opportunity:
    title = clean_text(item.title, limit=400)
    summary = clean_text(item.summary)
    organization = clean_text(item.organization, limit=200)
    categories = [clean_text(category, limit=80) for category in item.categories if category.strip()]
    classification = classify_text(title, summary, categories)
    url = canonical_url(item.url)
    fields = classification.fields
    match_text = " ".join(
        part
        for part in (title, summary, organization, " ".join(categories), " ".join(fields))
        if part
    ).lower()
    return Opportunity(
        id=opportunity_id(url),
        source_id=item.source_id,
        title=title,
        url=url,
        summary=summary,
        organization=organization,
        published_at=item.published_at,
        fetched_at=now,
        degree_levels=classification.degree_levels,
        opportunity_types=classification.opportunity_types,
        countries=classification.countries,
        fields=fields,
        funding=classification.funding,
        deadline=classification.deadline,
        confidence=classification.confidence,
        is_actionable=classification.is_actionable,
        match_text=match_text,
        title_key=title_key(title),
        content_hash=content_hash(title, summary),
    )
