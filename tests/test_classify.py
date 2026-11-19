from datetime import date

from scholarship_agent.classify import classify_text, deadline_phrase, extract_deadline, opening_phrase, schedule_notes


def test_phd_opening_is_not_confused_with_a_job_that_requires_a_phd():
    opening = classify_text(
        "PhD position - Quantum Sensing of Radical Chemistry in Biomimetic Thin Films",
        "A fully funded PhD position. Deadline: 15 January 2027.",
    )
    employed = classify_text(
        "FEUP - Entry-Level PhD Researcher - Project InnovAntiBiofilm",
        "Fixed-term employment contract for a researcher who already holds a PhD.",
    )
    faculty = classify_text(
        "Assistant Professor",
        "The duties include supervision of PhD students in the department.",
    )
    postdoc = classify_text("Call for Postdoctoral Research Assignment", "")

    assert opening.degree_levels == ["phd"]
    assert "position" in opening.opportunity_types
    assert opening.funding == "fully_funded"
    assert opening.deadline is not None and opening.deadline.isoformat() == "2027-01-15"
    assert opening.is_actionable
    stated = classify_text("Vanier Canada Graduate Scholarships", "The deadline is before 30 October 2024.")
    assert stated.deadline is not None and stated.deadline.isoformat() == "2024-10-30"

    assert employed.degree_levels == ["researcher"]
    assert "phd" not in employed.degree_levels
    assert faculty.degree_levels == ["faculty"]
    assert "phd" not in faculty.degree_levels
    assert postdoc.degree_levels == ["postdoc"]


def test_masters_scholarship_extracts_countries_fields_and_funding():
    result = classify_text(
        "2027 TCCM Masters Scholarship in Spain, France, Netherlands, Italy | Fully Funded",
        "The award covers tuition and a stipend.",
        ["Masters Scholarships", "Chemistry", "Fully Funded"],
    )
    assert result.degree_levels == ["masters"]
    assert "scholarship" in result.opportunity_types
    assert result.funding == "fully_funded"
    assert result.fields == ["Chemistry"]
    assert {"Spain", "France", "Netherlands", "Italy"} <= set(result.countries)
    assert result.is_actionable


def test_a_named_scholarship_stays_listed_when_the_title_says_how_to_apply():
    award = classify_text(
        "2027 Chinese Government Scholarship Program | How to Apply",
        "A fully funded scholarship for bachelor, master and PhD programs in China.",
    )
    roundup = classify_text("6 Scholarships That Can Help You Study Abroad With Family", "")

    assert award.is_actionable
    assert {"bachelor", "masters", "phd"} <= set(award.degree_levels)
    assert "China" in award.countries
    assert roundup.is_actionable is False
    listicle = classify_text(
        "7 Universities in the Netherlands Offering English-Taught Bachelor's Programmes (2027)",
        "A roundup of universities.",
        ["Blog", "Study Abroad"],
    )
    fellowship = classify_text("Equality Fund Journalism Fellowship 2027", "A $4,000 stipend.")

    assert listicle.is_actionable is False
    assert "guide" in listicle.opportunity_types
    assert fellowship.degree_levels == []
    assert "scholarship" in fellowship.opportunity_types


def test_predoctoral_contract_is_a_phd_opening_and_non_doctoral_is_not():
    opening = classify_text("4-year predoctoral contract in chemistry", "")
    employed = classify_text("Postgraduate non-doctoral researcher", "A non-doctoral position in the lab.")
    hired = classify_text("NOTICE TO HIRE A PHD RESEARCHER", "")

    assert opening.degree_levels == ["phd"]
    assert "position" in opening.opportunity_types
    assert "phd" not in employed.degree_levels
    assert hired.degree_levels == ["researcher"]


def test_deadline_opening_and_degree_stay_specific():
    notice = "Applications are currently open. Deadline: November 30, 2026. A master's scholarship."
    assert extract_deadline(notice).isoformat() == "2026-11-30"
    assert deadline_phrase(notice) == "30 November 2026"
    assert opening_phrase(notice, date(2026, 11, 30), today=date(2026, 11, 6)) == "Open now"
    timed = "Application Deadline: 16 Nov 2026 - 23:59 (Europe/Prague)"
    assert deadline_phrase(timed) == "16 November 2026, 23:59 (Europe/Prague)"
    assert deadline_phrase("Deadline: Open All Year") == "Open all year"
    assert opening_phrase("Deadline: Open All Year") == "Open all year"
    assert deadline_phrase("Deadline: Varies by Institution") == "Varies by institution"
    notes = schedule_notes(
        "A long essay about campus life. Deadline: 15th January 2027. The award is for PhD students."
    )
    assert "15th January 2027" in notes or "15 January 2027" in notes
    assert "PhD" in notes
    assert "campus life" not in notes
    classified = classify_text("Open scholarship", notes)
    assert classified.deadline is not None and classified.deadline.isoformat() == "2027-01-15"
    assert "phd" in classified.degree_levels


def test_body_can_supply_the_degree_when_the_title_does_not():
    result = classify_text(
        "Open scholarship",
        "This is a master's scholarship for international students.",
    )
    assert result.degree_levels == ["masters"]
    assert result.confidence < 0.8
