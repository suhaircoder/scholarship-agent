from datetime import datetime, timezone

from scholarship_agent.channels import build_email
from scholarship_agent.models import Digest, DigestItem
from scholarship_agent.render import render_html, render_telegram_messages

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _digest() -> Digest:
    return Digest(
        profile_id="me",
        display_name="Me",
        generated_at=NOW,
        items=[
            DigestItem(
                match_id=1,
                title='PhD <script>alert("x")</script>',
                url="https://example.org/phd?q=1",
                source_id="euraxess",
                summary="A short excerpt.",
                score=80,
                reasons=["Degree matches: phd"],
            )
        ],
        channel="file",
    )


def test_html_digest_escapes_titles():
    page = render_html(_digest())
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "https://example.org/phd?q=1" in page


def test_telegram_messages_split_long_digests():
    digest = _digest().model_copy(
        update={
            "items": [
                _digest().items[0].model_copy(update={"title": "A" * 30, "match_id": index})
                for index in range(4)
            ]
        }
    )
    messages = render_telegram_messages(digest, limit=120)
    assert len(messages) > 1
    assert all("<b>Me</b>" in message for message in messages)


def test_email_contains_plain_and_html_parts():
    message = build_email(sender="bot@example.org", recipient="me@example.org", digest=_digest())
    assert message["Subject"] == "1 academic match for Me"
    assert message.get_body(preferencelist=("plain",)) is not None
    assert message.get_body(preferencelist=("html",)) is not None
