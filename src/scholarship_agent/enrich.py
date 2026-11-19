"""Optional OpenAI-compatible reading of listings the rules are unsure about."""

from __future__ import annotations

import json
import re
from datetime import date

import httpx
from pydantic import BaseModel, Field, ValidationError

from scholarship_agent.errors import EnrichmentError
from scholarship_agent.locations import canonicalize_country
from scholarship_agent.models import Opportunity
from scholarship_agent.profiles import ALLOWED_DEGREES, ALLOWED_FUNDING, ALLOWED_TYPES
from scholarship_agent.textutil import clean_text

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_SYSTEM = """You classify academic opportunity posts for a personal digest.
Reply with one JSON object and no other text.
Use only these degree_levels: phd, masters, bachelor, postdoc, researcher, faculty.
phd means a place to start a PhD. A job that requires an existing PhD is researcher or postdoc or faculty, not phd.
Use only these opportunity_types: position, scholarship, fellowship, guide.
guide means a listicle, news item, or advice article rather than something a person can apply to.
funding is fully_funded, partial, or unknown.
countries are English country names.
summary is one sentence, at most 40 words.
confidence is a number from 0 to 1.
deadline is YYYY-MM-DD or null.
is_actionable is false for guides and news."""


class LlmAssessment(BaseModel):
    degree_levels: list[str] = Field(default_factory=list)
    opportunity_types: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    funding: str = "unknown"
    deadline: str | None = None
    is_actionable: bool = True
    summary: str = ""
    confidence: float = 0.0


class NoopEnricher:
    enabled = False

    def enrich(self, opportunity: Opportunity) -> Opportunity:
        return opportunity


class OpenAICompatibleEnricher:
    enabled = True

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def enrich(self, opportunity: Opportunity) -> Opportunity:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _user_prompt(opportunity)},
            ],
        }
        try:
            body = self._complete(payload)
            content = body["choices"][0]["message"]["content"]
            assessment = parse_assessment(content)
        except EnrichmentError:
            raise
        except (KeyError, IndexError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise EnrichmentError("The model returned an unreadable classification") from exc
        except Exception as exc:
            raise EnrichmentError("The model request failed") from exc
        return apply_assessment(opportunity, assessment)


    def _complete(self, payload: dict) -> dict:
        response = self._client.post("/chat/completions", json=payload)
        if response.status_code == 400 and "response_format" in payload:
            reduced = dict(payload)
            reduced.pop("response_format")
            response = self._client.post("/chat/completions", json=reduced)
        if response.status_code >= 400:
            raise EnrichmentError(f"The model request failed with status {response.status_code}")
        return response.json()


def parse_assessment(content: str) -> LlmAssessment:
    text = _FENCE.sub("", content.strip())
    return LlmAssessment.model_validate(json.loads(text))


def apply_assessment(opportunity: Opportunity, assessment: LlmAssessment) -> Opportunity:
    if assessment.confidence < opportunity.confidence:
        return opportunity.model_copy(update={"enriched": True})
    degrees = [item for item in assessment.degree_levels if item in ALLOWED_DEGREES]
    types = [item for item in assessment.opportunity_types if item in ALLOWED_TYPES]
    if not assessment.is_actionable and "guide" not in types:
        types.append("guide")
    funding = assessment.funding if assessment.funding in ALLOWED_FUNDING else opportunity.funding
    countries: list[str] = []
    for name in assessment.countries:
        canonical = canonicalize_country(name)
        label = canonical or clean_text(name, limit=60)
        if label and label not in countries:
            countries.append(label)
    deadline = _date(assessment.deadline) or opportunity.deadline
    summary = clean_text(assessment.summary, limit=400)
    fields = [clean_text(item, limit=80) for item in assessment.fields if clean_text(item, limit=80)]
    return opportunity.model_copy(
        update={
            "degree_levels": degrees or opportunity.degree_levels,
            "opportunity_types": types or opportunity.opportunity_types,
            "countries": countries or opportunity.countries,
            "fields": fields or opportunity.fields,
            "funding": funding,
            "deadline": deadline,
            "is_actionable": assessment.is_actionable,
            "ai_summary": summary or opportunity.ai_summary,
            "confidence": max(0.0, min(1.0, assessment.confidence)),
            "enriched": True,
        }
    )


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _user_prompt(opportunity: Opportunity) -> str:
    return "\n".join(
        [
            f"Title: {opportunity.title}",
            f"Source: {opportunity.source_id}",
            f"Organization: {opportunity.organization}",
            f"Categories: {', '.join(opportunity.fields)}",
            f"Excerpt: {opportunity.summary[:1500]}",
        ]
    )
