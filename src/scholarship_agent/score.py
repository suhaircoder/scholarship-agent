"""Decide whether a listing belongs in one person's digest."""

from __future__ import annotations

from datetime import date

from scholarship_agent.classify import extract_deadline
from scholarship_agent.locations import canonicalize_country
from scholarship_agent.models import Opportunity, ScoreDecision
from scholarship_agent.profiles import UserProfile
from scholarship_agent.textutil import term_in_text


def _wanted_countries(profile: UserProfile) -> set[str]:
    wanted: set[str] = set()
    for name in profile.countries:
        canonical = canonicalize_country(name)
        wanted.add(canonical or name.strip().lower())
    return wanted


def score_opportunity(
    profile: UserProfile,
    opportunity: Opportunity,
    today: date,
) -> ScoreDecision:
    if opportunity.duplicate_of:
        return ScoreDecision(accepted=False, score=0, reject_reason="Duplicate of another listing")
    if not opportunity.is_actionable or "guide" in opportunity.opportunity_types:
        return ScoreDecision(accepted=False, score=0, reject_reason="Not a direct listing")
    deadline = opportunity.deadline or extract_deadline(opportunity.match_text)
    if deadline and deadline < today:
        return ScoreDecision(accepted=False, score=0, reject_reason="Deadline has passed")

    degrees = set(opportunity.degree_levels)
    types = set(opportunity.opportunity_types)
    broad_search = {"phd", "masters", "bachelor"} <= set(profile.degree_levels)
    if not degrees:
        if not (broad_search and types & {"scholarship", "fellowship"}):
            return ScoreDecision(accepted=False, score=0, reject_reason="Degree level is unclear")
    elif not degrees & set(profile.degree_levels):
        return ScoreDecision(
            accepted=False,
            score=0,
            reject_reason=f"Degree {', '.join(sorted(degrees))} is outside this profile",
        )

    types = set(opportunity.opportunity_types)
    if not types:
        return ScoreDecision(accepted=False, score=0, reject_reason="Listing type is unclear")
    overlap = types & set(profile.opportunity_types)
    if not overlap:
        return ScoreDecision(
            accepted=False,
            score=0,
            reject_reason=f"Type {', '.join(sorted(types))} is outside this profile",
        )

    if opportunity.funding != "unknown" and opportunity.funding not in profile.funding_preference:
        return ScoreDecision(
            accepted=False,
            score=0,
            reject_reason=f"Funding {opportunity.funding} is outside this profile",
        )
    if (
        opportunity.funding == "unknown"
        and not profile.allow_unknown_funding
        and "unknown" not in profile.funding_preference
    ):
        return ScoreDecision(accepted=False, score=0, reject_reason="Funding is not stated")

    for blocked in profile.keywords_exclude:
        if term_in_text(blocked, opportunity.title):
            return ScoreDecision(accepted=False, score=0, reject_reason=f"Title contains '{blocked}'")

    if profile.keywords_include and not any(
        term_in_text(term, opportunity.match_text) for term in profile.keywords_include
    ):
        return ScoreDecision(accepted=False, score=0, reject_reason="None of the required keywords matched")

    discipline_hits = [
        term for term in profile.disciplines if term_in_text(term, opportunity.match_text)
    ]
    listed_countries = {canonicalize_country(name) or name for name in opportunity.countries}
    for term in profile.disciplines:
        canonical = canonicalize_country(term)
        if canonical and canonical in listed_countries and canonical not in discipline_hits:
            discipline_hits.append(canonical)
    if profile.disciplines and profile.require_discipline_match and not discipline_hits:
        return ScoreDecision(accepted=False, score=0, reject_reason="None of the disciplines matched")

    wanted = _wanted_countries(profile)
    found = {canonicalize_country(name) or name for name in opportunity.countries}
    country_hit = sorted(wanted & found) if wanted else []
    if wanted and found and not country_hit:
        return ScoreDecision(
            accepted=False,
            score=0,
            reject_reason=f"Country {', '.join(opportunity.countries)} is outside this profile",
        )

    if degrees:
        matched = ", ".join(sorted(degrees & set(profile.degree_levels)))
        reasons = [f"Degree matches: {matched}"]
    else:
        reasons = ["Scholarship, degree not stated in the excerpt"]
    reasons.append(f"Listing type matches: {', '.join(sorted(overlap))}")
    score = 70.0
    if opportunity.funding in profile.funding_preference and opportunity.funding != "unknown":
        score += 15
        label = "fully funded" if opportunity.funding == "fully_funded" else "partial funding"
        reasons.append(f"Funding: {label}")
    if wanted and country_hit:
        score += 10
        reasons.append(f"Country: {', '.join(country_hit)}")
    elif not wanted:
        score += 10
        reasons.append("Global search")
    elif wanted and not found:
        score -= 10
        reasons.append("Country was not stated")
    if discipline_hits:
        score += min(20, 10 * len(discipline_hits))
        reasons.append(f"Discipline: {', '.join(discipline_hits)}")
    if any(term_in_text(term, opportunity.match_text) for term in profile.keywords_include):
        score += 10
        reasons.append("A required keyword matched")

    score = max(0.0, min(100.0, score))
    if score < profile.min_score:
        return ScoreDecision(
            accepted=False,
            score=score,
            reasons=reasons,
            reject_reason=f"Score {score:.0f} is below {profile.min_score:.0f}",
        )
    return ScoreDecision(accepted=True, score=score, reasons=reasons)
