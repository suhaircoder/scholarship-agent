from datetime import datetime, timezone

from scholarship_agent.agent import OpportunityAgent
from scholarship_agent.errors import DeliveryError
from scholarship_agent.models import RawItem
from scholarship_agent.profiles import Settings, SourceConfig, UserProfile
from scholarship_agent.storage import Repository

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

ITEMS = [
    RawItem(
        source_id="example",
        title="PhD position in coastal modelling",
        url="https://example.org/phd",
        summary="A fully funded PhD position.",
    ),
    RawItem(
        source_id="example",
        title="Masters Scholarship in Public Health",
        url="https://example.org/msc",
        summary="A fully funded master's scholarship.",
        categories=["Public Health"],
    ),
    RawItem(
        source_id="example",
        title="Assistant Professor",
        url="https://example.org/faculty",
        summary="Supervision of PhD students is part of the role.",
    ),
    RawItem(
        source_id="example",
        title="7 Universities Offering English-Taught Bachelor's Programmes",
        url="https://example.org/list",
        summary="A roundup, not an application.",
        categories=["Blog"],
    ),
]


class FakeScrapers:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def fetch(self, source):
        self.calls += 1
        return self.items


class RecordingChannel:
    def __init__(self, name="file"):
        self.name = name
        self.digests = []

    def handles(self, profile):
        return True

    def deliver(self, profile, digest):
        self.digests.append((profile.id, [item.title for item in digest.items]))


class FailingChannel:
    name = "email"

    def __init__(self) -> None:
        self.calls = 0

    def handles(self, profile):
        return profile.id == "me"

    def deliver(self, profile, digest):
        self.calls += 1
        raise DeliveryError("mailbox unavailable")


def _profiles():
    return [
        UserProfile(
            id="me",
            display_name="Me",
            degree_levels=["phd"],
            opportunity_types=["position", "scholarship"],
        ),
        UserProfile(
            id="sister",
            display_name="Sister",
            degree_levels=["masters"],
            opportunity_types=["scholarship"],
        ),
    ]


def _agent(repository, scrapers, distributors):
    return OpportunityAgent(
        settings=Settings(),
        profiles=_profiles(),
        sources=[SourceConfig(id="example", type="rss", url="https://example.org/feed")],
        repository=repository,
        scrapers=scrapers,
        distributors=distributors,
        clock=lambda: NOW,
    )


def test_each_person_receives_only_their_listings(tmp_path):
    channel = RecordingChannel()
    with Repository(tmp_path / "agent.db") as repository:
        agent = _agent(repository, FakeScrapers(ITEMS), [channel])
        report = agent.run()
        assert report.delivered == 2
        delivered = {profile_id: titles for profile_id, titles in channel.digests}
        assert delivered["me"] == ["PhD position in coastal modelling"]
        assert delivered["sister"] == ["Masters Scholarship in Public Health"]

        channel.digests.clear()
        second = agent.run()
        assert second.delivered == 0
        assert channel.digests == []


def test_a_failed_channel_is_retried_and_a_successful_one_is_not(tmp_path):
        files = RecordingChannel("file")
        email = FailingChannel()
        with Repository(tmp_path / "agent.db") as repository:
            agent = _agent(repository, FakeScrapers(ITEMS), [files, email])
            agent.run()
            assert email.calls == 1
            files.digests.clear()
            agent.run()
            assert files.digests == []
            assert email.calls == 2


def test_dry_run_discards_what_it_collected(tmp_path):
    with Repository(tmp_path / "agent.db") as repository:
        agent = _agent(repository, FakeScrapers(ITEMS), [RecordingChannel()])
        report = agent.run(dry_run=True)
        assert report.dry_run
        assert any(line.startswith("Me:") and "PhD position" in line for line in report.previews)
        count = repository.conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        assert count == 0
