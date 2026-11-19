from scholarship_agent.wordpress import parse_wp_posts

PAYLOAD = """
[
  {
    "link": "https://www.scholarshipregion.com/kaust-scholarship/",
    "date": "2026-10-01T09:00:00",
    "title": {"rendered": "2027 KAUST &#8211; King Abdullah University Scholarship in Saudi Arabia (Fully Funded)"},
    "excerpt": {"rendered": "<p>A fully funded master's and PhD scholarship in Saudi Arabia.</p>"}
  },
  {
    "link": "https://www.scholarshipregion.com/kaust-scholarship/",
    "title": {"rendered": "duplicate"},
    "excerpt": {"rendered": ""}
  }
]
"""


def test_wordpress_posts_keep_the_deadline_and_not_the_whole_article():
    payload = """
    [{
      "link": "https://www.scholarshipregion.com/eth-zurich/",
      "date": "2026-10-01T09:00:00",
      "title": {"rendered": "ETH Zurich Excellence Scholarship"},
      "excerpt": {"rendered": "<p>A master's scholarship at ETH Zurich.</p>"},
      "content": {"rendered": "<p>The zebra campus picnic lasts for many pages and is not the scholarship.</p><p>Deadline: November 30, 2026. Applications are currently open.</p>"}
    }]
    """
    items = parse_wp_posts(payload, "scholarship_region_europe")
    assert len(items) == 1
    assert "November 30, 2026" in items[0].summary
    assert "currently open" in items[0].summary.lower()
    assert "zebra campus picnic" not in items[0].summary


def test_wordpress_posts_keep_the_title_and_excerpt_only():
    items = parse_wp_posts(PAYLOAD, "scholarship_region_saudi")
    assert len(items) == 1
    assert items[0].title.startswith("2027 KAUST")
    assert "&#" not in items[0].title
    assert "<p>" not in items[0].summary
    assert "Saudi Arabia" in items[0].summary
    assert items[0].published_at is not None
