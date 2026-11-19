import json

from scholarship_agent.enrich import apply_assessment, parse_assessment
from scholarship_agent.models import Opportunity
from datetime import datetime, timezone


def _opportunity() -> Opportunity:
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    return Opportunity(
        id="abc",
        source_id="euraxess",
        title="Research opening",
        url="https://example.org/jobs/9",
        summary="A vague post.",
        fetched_at=now,
        confidence=0.4,
        match_text="research opening",
        title_key="research opening",
        content_hash="hash",
    )


def test_parse_assessment_accepts_fenced_json():
    raw = """```json
    {"degree_levels":["phd"],"opportunity_types":["position"],"countries":["Switzerland"],
     "funding":"fully_funded","is_actionable":true,"summary":"Funded doctoral opening.",
     "confidence":0.91,"deadline":"2027-03-01","fields":["Physics"]}
    ```"""
    assessment = parse_assessment(raw)
    updated = apply_assessment(_opportunity(), assessment)
    assert updated.degree_levels == ["phd"]
    assert updated.countries == ["Switzerland"]
    assert updated.funding == "fully_funded"
    assert updated.deadline is not None and updated.deadline.isoformat() == "2027-03-01"
    assert updated.ai_summary == "Funded doctoral opening."
    assert updated.enriched


def test_low_confidence_model_output_does_not_replace_a_stronger_reading():
    opportunity = _opportunity().model_copy(update={"confidence": 0.92, "degree_levels": ["phd"]})
    assessment = parse_assessment(json.dumps({"degree_levels": ["masters"], "confidence": 0.2}))
    updated = apply_assessment(opportunity, assessment)
    assert updated.degree_levels == ["phd"]
    assert updated.enriched
