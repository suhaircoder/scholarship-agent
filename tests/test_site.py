from scholarship_agent.models import Opportunity, PendingMatch
from scholarship_agent.profiles import UserProfile
from scholarship_agent.site import _department_label, render_portfolio, render_site
from datetime import datetime, timezone


def _profile(profile_id: str, name: str, degree: str) -> UserProfile:
    return UserProfile(
        id=profile_id,
        display_name=name,
        degree_levels=[degree],
        opportunity_types=["scholarship"],
    )


def test_site_lists_each_person_and_escapes_titles():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    me = _profile("me", "Me", "phd")
    sister = _profile("sister", "Sister", "masters")
    match = PendingMatch(
        match_id=1,
        score=80,
        reasons=["Degree matches: phd"],
        opportunity=Opportunity(
            id="abc",
            source_id="euraxess",
            title='PhD <script>alert("x")</script>',
            url="https://example.org/phd?q=1",
            summary="A short excerpt.",
            fetched_at=now,
        ),
    )
    page = render_site([me, sister], "me", {"me": [match], "sister": []})
    assert 'href="/me"' in page
    assert 'href="/sister"' in page
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "https://example.org/phd?q=1" in page
    assert "PhD positions" not in page or "PhD scholarship" in page


def test_browse_separates_country_and_department():
    me = _profile("me", "Me", "phd")
    page = render_site(
        [me],
        "browse",
        {"browse": []},
        department_text="Engineering",
        degree="all",
        country="Saudi Arabia",
    )
    assert 'name="country"' in page
    assert "Saudi Arabia" in page
    assert "France" in page
    assert "Japan" in page
    assert "Nigeria" in page
    assert 'name="field"' in page
    assert 'placeholder="Computer science, law, medicine"' in page
    assert 'value="Engineering"' in page
    assert "<select name=\"field\"" not in page
    assert "All scholarships" in page
    assert "No scholarship states Saudi Arabia Engineering" in page


def test_card_states_when_it_opens_the_deadline_and_the_degree():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    me = _profile("me", "Me", "phd")
    match = PendingMatch(
        match_id=1,
        score=80,
        reasons=["Degree matches: masters"],
        opportunity=Opportunity(
            id="eth",
            source_id="scholarship_region",
            title="ETH Zurich Excellence Scholarship",
            url="https://example.org/eth",
            summary="Deadline: November 30, 2026. Applications are currently open. A master's scholarship.",
            fetched_at=now,
            degree_levels=["masters"],
            funding="fully_funded",
            deadline=datetime(2026, 11, 30).date(),
        ),
    )
    page = render_site([me], "me", {"me": [match]})
    assert ">Opens</dt><dd>Open now</dd>" in page
    assert ">Deadline</dt><dd>30 November 2026</dd>" in page
    assert "Master" in page
    assert ">Deadline</dt><dd>Not stated</dd>" not in page
    assert ">Degree</dt><dd>Not stated</dd>" not in page
    assert 'href="/portfolio"' in page
    assert "Save to portfolio" in page


def test_cv_search_lists_every_opening_and_puts_the_field_first():
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    me = _profile("me", "PhD", "phd")

    def item(item_id: str, title: str) -> PendingMatch:
        return PendingMatch(
            match_id=1,
            score=80,
            reasons=[],
            opportunity=Opportunity(
                id=item_id,
                source_id="euraxess",
                title=title,
                url=f"https://example.org/{item_id}",
                summary="A funded opening.",
                fetched_at=now,
                degree_levels=["phd"],
                opportunity_types=["position"],
            ),
        )

    page = render_site(
        [me],
        "browse",
        {
            "browse": [
                item("hist", "PhD position in medieval history"),
                item("cs", "PhD scholarship in computer science"),
            ]
        },
        department_text="computer science",
        degree="phd",
        from_cv=True,
        cv_reason="completed-master",
    )
    assert page.index("computer science") < page.index("medieval history")
    assert "Every other open listing" in page
    assert "finished master's" in page


def test_portfolio_board_groups_saved_scholarships():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    me = _profile("me", "Me", "phd")
    item = Opportunity(
        id="abc",
        source_id="example",
        title="KAUST Scholarship",
        url="https://example.org/kaust",
        summary="Deadline: January 3, 2027. A master's and PhD scholarship.",
        fetched_at=now,
        degree_levels=["masters", "phd"],
        funding="fully_funded",
        deadline=datetime(2027, 1, 3).date(),
        countries=["Saudi Arabia"],
    )
    page = render_portfolio([me], {"me": []}, [], [("saved", item)], 1)
    assert "Portfolio" in page
    assert "KAUST Scholarship" in page
    assert "Start applying" in page
    assert "Saudi Arabia" in page


def test_department_is_written_from_the_scholarship_itself():
    assert _department_label("Scholarship at the Faculty of Law", "", []) == "Law"
    assert _department_label("Open scholarship", "Students in any field may apply.", []) == "All departments"
    assert _department_label("PhD in any faculty at Imperial College London", "", []) == "All departments"
    assert (
        _department_label(
            "PhD researcher in the scientific area of Food Technology",
            "",
            [],
        )
        == "Food Technology"
    )
    assert _department_label("University of Wyoming Masters Scholarship", "A funded master's program.", []) == (
        "Not named in the notice"
    )
    assert "Engineering" in _department_label("Civil engineering scholarship", "", [])
