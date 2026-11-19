from datetime import date, datetime, timezone

from scholarship_agent.models import RawItem
from scholarship_agent.prepare import prepare_opportunity
from scholarship_agent.profiles import UserProfile
from scholarship_agent.score import score_opportunity

TODAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


def _profile(**overrides) -> UserProfile:
    data = {
        "id": "me",
        "display_name": "Me",
        "degree_levels": ["phd"],
        "opportunity_types": ["position", "scholarship"],
    }
    data.update(overrides)
    return UserProfile(**data)


def _opportunity(title: str, summary: str = "", categories: list[str] | None = None):
    return prepare_opportunity(
        RawItem(
            source_id="example",
            title=title,
            url="https://example.org/jobs/1",
            summary=summary,
            categories=categories or [],
        ),
        NOW,
    )


def test_phd_opening_passes_and_masters_scholarship_does_not():
    me = _profile()
    sister = _profile(
        id="sister",
        display_name="Sister",
        degree_levels=["masters"],
        opportunity_types=["scholarship"],
    )
    phd = _opportunity("PhD position in coastal modelling", "Fully funded for three years.")
    masters = _opportunity(
        "Masters Scholarship in Public Health",
        "A fully funded master's scholarship.",
        ["Public Health"],
    )

    assert score_opportunity(me, phd, TODAY).accepted
    assert not score_opportunity(sister, phd, TODAY).accepted
    assert score_opportunity(sister, masters, TODAY).accepted
    assert not score_opportunity(me, masters, TODAY).accepted


def test_discipline_country_and_deadline_filters():
    focused = _profile(disciplines=["computer science"], countries=["Germany"])
    computer = _opportunity(
        "PhD position in computer science",
        "Based in Germany. Deadline: 2 December 2026.",
    )
    history = _opportunity("PhD position in medieval history", "Based in Germany.")
    france = _opportunity("PhD position in computer science", "The lab is in France.")
    expired = _opportunity(
        "PhD position in computer science",
        "Based in Germany. Deadline: 1 January 2020.",
    )

    assert score_opportunity(focused, computer, TODAY).accepted
    assert "computer science" in score_opportunity(focused, computer, TODAY).reasons[-1]
    assert not score_opportunity(focused, history, TODAY).accepted
    assert not score_opportunity(focused, france, TODAY).accepted
    assert not score_opportunity(focused, expired, TODAY).accepted


def test_strict_funding_rejects_partial_awards():
    strict = _profile(funding_preference=["fully_funded"], allow_unknown_funding=False)
    partial = _opportunity("PhD scholarship", "This is a tuition waiver only.")
    hidden = _opportunity("PhD position in chemistry", "The department is hiring a student.")

    assert partial.funding == "partial"
    assert not score_opportunity(strict, partial, TODAY).accepted
    assert not score_opportunity(strict, hidden, TODAY).accepted
