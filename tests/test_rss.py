from scholarship_agent.rss import parse_rss

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example</title>
    <item>
      <title>Older post</title>
      <link>https://example.org/old?utm_source=feed</link>
      <description>Second</description>
      <pubDate>Wed, 04 Sep 2026 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>PhD position - Coastal AI</title>
      <link>https://example.org/jobs/1</link>
      <description><![CDATA[A <b>fully funded</b> PhD position.]]></description>
      <pubDate>Thu, 05 Nov 26 13:37:31 +0200</pubDate>
      <dc:creator>Adolphe Merkle Institute</dc:creator>
      <category>Computer Science</category>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_keeps_the_newest_items_and_reads_a_two_digit_year():
    items = parse_rss(SAMPLE, "euraxess", max_items=1)
    assert len(items) == 1
    item = items[0]
    assert item.title == "PhD position - Coastal AI"
    assert item.url == "https://example.org/jobs/1"
    assert item.organization == "Adolphe Merkle Institute"
    assert item.categories == ["Computer Science"]
    assert "fully funded" in item.summary.lower()
    assert item.published_at is not None
    assert item.published_at.year == 2026


def test_parse_rss_rejects_a_feed_with_no_entries():
    import pytest

    from scholarship_agent.errors import SourceFetchError

    with pytest.raises(SourceFetchError):
        parse_rss("<rss><channel><title>Broken", "broken", max_items=10)
