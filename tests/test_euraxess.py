from scholarship_agent.euraxess import parse_euraxess_listings

PAGE = """
<html><body>
<a href="/jobs/12345">4-year predoctoral contract in chemistry</a>
<a href="/jobs/12345">4-year predoctoral contract in chemistry</a>
<a href="https://euraxess.ec.europa.eu/jobs/99">Apply</a>
<a href="/jobs/88">Research Studentships for students of a PhD</a>
</body></html>
"""


def test_euraxess_page_keeps_job_titles_and_drops_apply_links():
    items = parse_euraxess_listings(PAGE, "euraxess_pages")
    assert [item.title for item in items] == [
        "4-year predoctoral contract in chemistry",
        "Research Studentships for students of a PhD",
    ]
    assert items[0].url == "https://euraxess.ec.europa.eu/jobs/12345"
    assert items[1].url == "https://euraxess.ec.europa.eu/jobs/88"


def test_euraxess_card_keeps_the_deadline_on_the_search_page():
    page = """
    <article class="ecl-content-item">
      <h3><a href="/jobs/478557"><span>PhD in chemistry</span></a></h3>
      <p>Research Field: Chemistry Researcher Profile: First Stage Researcher (R1)</p>
      <p>Application Deadline: 16 Nov 2026 - 23:59 (Europe/Prague)</p>
    </article>
    """
    items = parse_euraxess_listings(page, "euraxess_pages")
    assert len(items) == 1
    assert items[0].title == "PhD in chemistry"
    assert "16 Nov 2026" in items[0].summary
    assert "23:59" in items[0].summary
    assert "Chemistry" in items[0].summary
