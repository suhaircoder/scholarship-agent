from datetime import datetime, timezone

from scholarship_agent.models import RawItem
from scholarship_agent.prepare import prepare_opportunity
from scholarship_agent.storage import Repository

NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


def _opportunity(url: str, title: str):
    return prepare_opportunity(
        RawItem(source_id="example", title=title, url=url, summary="A fully funded PhD position."),
        NOW,
    )


def test_round_trip_and_unchanged_repost(tmp_path):
    with Repository(tmp_path / "agent.db") as repository:
        opportunity = _opportunity("https://example.org/jobs/1", "PhD position in glacier hydrology")
        stored, changed = repository.upsert_opportunity(opportunity)
        again, changed_again = repository.upsert_opportunity(opportunity)
        repository.commit()
        assert changed
        assert not changed_again
        assert repository.get_by_url(stored.url).title == opportunity.title


def test_portfolio_keeps_a_scholarship_until_it_is_removed(tmp_path):
    with Repository(tmp_path / "agent.db") as repository:
        opportunity = _opportunity("https://example.org/jobs/9", "PhD scholarship in coastal engineering")
        repository.upsert_opportunity(opportunity)
        repository.save_to_portfolio(opportunity.id, NOW)
        repository.save_to_portfolio(opportunity.id, NOW)
        repository.commit()
        assert repository.list_portfolio() == [(opportunity.id, "saved")]
        repository.set_portfolio_status(opportunity.id, "applying")
        repository.commit()
        assert repository.list_portfolio() == [(opportunity.id, "applying")]
        repository.remove_from_portfolio(opportunity.id)
        repository.commit()
        assert repository.list_portfolio() == []


def test_distinctive_titles_can_be_marked_as_cross_posts(tmp_path):
    with Repository(tmp_path / "agent.db") as repository:
        title = "Fully funded doctoral scholarship in renewable energy systems for international students"
        first = _opportunity("https://example.org/a", title)
        second = _opportunity("https://example.org/b", title)
        repository.upsert_opportunity(first)
        canonical = repository.find_canonical_url(second.title_key, second.url)
        assert canonical == first.url
        repository.upsert_opportunity(second.model_copy(update={"duplicate_of": canonical}))
        repository.commit()
        assert len(repository.list_opportunities()) == 1
