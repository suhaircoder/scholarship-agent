"""Local pages for the matches already stored for each person."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from scholarship_agent.classify import deadline_phrase, extract_deadline, opening_phrase
from scholarship_agent.cv import MAX_CV_BYTES, CvReadError, read_cv, uploaded_file
from scholarship_agent.locations import all_country_names, canonicalize_country
from scholarship_agent.models import PendingMatch
from scholarship_agent.profiles import Department, UserProfile, profile_for_query, search_terms
from scholarship_agent.score import score_opportunity
from scholarship_agent.textutil import term_in_text

_NOISE = re.compile(
    r"\bhow\b.{0,80}\bwon\b|\bhere is how\b|\b\d+\s+countries\b|\btop\s+\d+\b|"
    r"\b\d+\s+(?:ongoing|best)\b|\bhow to identify\b|\belfmo_\d|\(bi\)|\breference\s+requimte\b",
    re.IGNORECASE,
)
_NAMED = re.compile(r"scholarship|fellowship|studentship|\bph\.?\s*d\b|\bmasters?\b|\bbachelor", re.IGNORECASE)
_FACULTY = re.compile(
    r"\b(?:department|faculty|school|college|institute)\s+of\s+([A-Za-z][A-Za-z &/-]{2,60})",
    re.IGNORECASE,
)
_AREA = re.compile(
    r"\b(?:scientific area|disciplinary area|research field|field|area)\s+of\s+([A-Za-z][A-Za-z &/-]{2,60})",
    re.IGNORECASE,
)
_CENTRE = re.compile(
    r"\b(?:centre|center)\s+for\s+([A-Za-z][A-Za-z &/-]{2,60})",
    re.IGNORECASE,
)
_PROGRAMME = re.compile(
    r"\b(?:master(?:'s)?|phd|doctorate|degree|programme|program)\s+in\s+([A-Za-z][A-Za-z &/-]{2,60})",
    re.IGNORECASE,
)
_OPEN_DEPARTMENT = re.compile(
    r"\b(?:any|all|every)\s+(?:field|fields|discipline|disciplines|major|majors|subject|subjects|"
    r"faculty|faculties|department|departments)\b|\bany area of study\b|\bevery field\b",
    re.IGNORECASE,
)
_GENERIC_FIELD = {
    "study",
    "studies",
    "research",
    "science",
    "scholarship",
    "scholarships",
    "programme",
    "program",
    "university",
    "students",
    "international",
    "the",
}
_FIELD_WORDS = (
    ("computer science", "Computer science"),
    ("artificial intelligence", "Computer science"),
    ("machine learning", "Computer science"),
    ("data science", "Computer science"),
    ("civil engineering", "Civil engineering"),
    ("mechanical engineering", "Mechanical engineering"),
    ("electrical engineering", "Electrical engineering"),
    ("chemical engineering", "Chemical engineering"),
    ("software engineering", "Software engineering"),
    ("engineering", "Engineering"),
    ("architecture", "Architecture"),
    ("agriculture", "Agriculture"),
    ("education", "Education"),
    ("law", "Law"),
    ("medicine", "Medicine"),
    ("medical", "Medicine"),
    ("nursing", "Nursing"),
    ("pharmacy", "Pharmacy"),
    ("public health", "Public health"),
    ("chemistry", "Chemistry"),
    ("biology", "Biology"),
    ("biotechnology", "Biotechnology"),
    ("physics", "Physics"),
    ("mathematics", "Mathematics"),
    ("maths", "Mathematics"),
    ("business", "Business"),
    ("economics", "Economics"),
    ("finance", "Finance"),
    ("management", "Management"),
    ("accounting", "Accounting"),
    ("psychology", "Psychology"),
    ("sociology", "Sociology"),
    ("history", "History"),
    ("literature", "Literature"),
    ("linguistics", "Linguistics"),
    ("environment", "Environmental science"),
    ("environmental", "Environmental science"),
    ("energy", "Energy"),
    ("materials", "Materials"),
    ("robotics", "Robotics"),
)
_ITEM_ID = re.compile(r"^[a-f0-9]{32}$")
_DEGREE_LABELS = {
    "phd": "PhD",
    "masters": "Master's",
    "bachelor": "Bachelor's",
    "postdoc": "Postdoc",
    "researcher": "Researcher",
    "faculty": "Faculty",
}


def linkedin_jobs_url(degree: str, keywords: list[str]) -> str:
    """LinkedIn does not publish a public feed. This opens their own job search."""
    level = {"phd": "PhD", "masters": "master scholarship"}.get(degree, "scholarship")
    focus = " ".join(keywords[:4])
    return "https://www.linkedin.com/jobs/search/?" + urlencode(
        {"keywords": f"{level} {focus}".strip(), "location": "Worldwide"}
    )


def live_matches(repository, profile: UserProfile) -> list[PendingMatch]:
    today = datetime.now(timezone.utc).date()
    found: list[PendingMatch] = []
    for opportunity in repository.list_opportunities():
        decision = score_opportunity(profile, opportunity, today)
        if not decision.accepted:
            continue
        found.append(
            PendingMatch(
                match_id=0,
                score=decision.score,
                reasons=decision.reasons,
                opportunity=opportunity,
                status="matched",
            )
        )
    found.sort(key=lambda item: item.score, reverse=True)
    return found


def render_site(
    profiles: list[UserProfile],
    active_id: str,
    matches_by_id: dict[str, list[PendingMatch]],
    departments: list[Department] | None = None,
    linkedin_url: str = "",
    department_text: str = "",
    degree: str = "all",
    country: str = "all",
    field_id: str = "",
    saved_ids: set[str] | None = None,
    return_to: str = "/browse?degree=all&country=all",
    portfolio_count: int = 0,
    from_cv: bool = False,
    cv_reason: str = "",
) -> str:
    departments = departments or []
    del linkedin_url, field_id
    saved_ids = saved_ids or set()
    active = next((profile for profile in profiles if profile.id == active_id), None)
    if active is None:
        active = profile_for_query(department_text, degree)
    matches = [match for match in matches_by_id.get(active_id, []) if _show(match)]
    nav = _navigation(profiles, active_id, matches_by_id, portfolio_count)
    cards, close_count = _cards(matches, country, departments, department_text, saved_ids, return_to, from_cv)
    title = "Scholarships" if active_id == "browse" else active.display_name
    count = len(matches)
    noun = "listing" if count == 1 else "listings"
    place = "every country" if country in {"", "all"} else country
    search = _search_box(country, department_text, degree, from_cv, cv_reason)
    if from_cv:
        lede = (
            f"{count} open scholarships and positions · {place}. "
            f"{close_count} mention the department on your CV. The rest are included too."
        )
    else:
        lede = (
            f"{count} {noun} · {place}. "
            "Each card states the degree, when it opens, and the deadline. "
            "Save the ones you will apply to."
        )
    return _document(title, nav, lede, search + cards)


def _document(title: str, nav: str, lede: str, body: str) -> str:
    safe_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} · Scholarship Agent</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1c1917;
      --muted: #57534e;
      --line: #e7e5e4;
      --paper: #faf7f2;
      --card: #fffdf8;
      --accent: #1f4d3a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", Palatino, serif;
      color: var(--ink);
      background: var(--paper);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 1.5rem;
      align-items: end;
      max-width: 1040px;
      margin: 0 auto;
      padding: 1.4rem 1.25rem 0.8rem;
    }}
    .brand {{
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .brand strong {{
      display: block;
      color: var(--ink);
      font-size: 1rem;
      letter-spacing: 0;
      text-transform: none;
      font-weight: 650;
    }}
    nav {{ display: flex; gap: 0.5rem; }}
    nav a {{
      color: var(--ink);
      text-decoration: none;
      border: 1px solid var(--line);
      background: transparent;
      border-radius: 999px;
      padding: 0.35rem 0.75rem;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.92rem;
    }}
    nav a.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
    nav span {{ opacity: 0.75; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 0.5rem 1.25rem 3rem; }}
    h1 {{ font-weight: normal; font-size: 2.4rem; margin: 0.2rem 0; }}
    .lede, .why, .org {{ color: var(--muted); }}
    .lede {{ margin-top: 0; }}
    article {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 1.15rem 1.2rem 1rem;
      margin: 0.85rem 0 0;
      box-shadow: 0 1px 0 rgba(28, 25, 23, 0.03);
    }}
    article.soon {{ border-color: #c2410c; }}
    .board {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.9rem;
      align-items: start;
    }}
    .column {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 0.85rem;
    }}
    .column h2 {{
      margin: 0 0 0.6rem;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.95rem;
      font-weight: 650;
    }}
    .column article {{ box-shadow: none; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.7rem; }}
    .actions button, .save button {{
      background: white;
      color: var(--accent);
      border-color: var(--accent);
    }}
    @media (max-width: 800px) {{
      .board {{ grid-template-columns: 1fr; }}
      header {{ align-items: start; flex-direction: column; }}
    }}
    .tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.78rem;
    }}
    .tags span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0.15rem 0.5rem;
    }}
    h3 {{ font-size: 1.25rem; font-weight: normal; margin: 0.2rem 0 0.35rem; }}
    .note {{ color: var(--muted); font-family: "Segoe UI", sans-serif; font-size: 0.92rem; }}
    h2 a {{ color: var(--accent); }}
    h2.country {{
      font-size: 1.6rem;
      font-weight: normal;
      margin: 1.8rem 0 0.2rem;
      padding-top: 0.6rem;
      border-top: 1px solid var(--line);
    }}
    dl {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.55rem 1rem;
      margin: 0.7rem 0;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.92rem;
    }}
    dt {{ color: var(--muted); font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; }}
    dd {{ margin: 0.1rem 0 0; }}
    .official {{ font-family: "Segoe UI", sans-serif; font-size: 0.88rem; }}
    .summary {{ line-height: 1.45; }}
    .empty {{ color: var(--muted); }}
    form.search {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: end;
      margin: 1rem 0;
      font-family: "Segoe UI", sans-serif;
    }}
    label {{ display: grid; gap: 0.25rem; font-size: 0.82rem; color: var(--muted); }}
    input, select, button {{
      font: inherit;
      color: var(--ink);
      background: white;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0.4rem 0.55rem;
    }}
    input[name="field"] {{ min-width: 16rem; }}
    button {{ background: var(--accent); color: white; border-color: var(--accent); cursor: pointer; }}
    .linkedin {{ font-family: "Segoe UI", sans-serif; }}
  </style>
</head>
<body>
  <header>
    <p class="brand"><strong>Scholarship Agent</strong>Find it, then keep it</p>
    <nav>{nav}</nav>
  </header>
  <main>
    <h1>{safe_title}</h1>
    <p class="lede">{html.escape(lede)}</p>
    {body}
  </main>
</body>
</html>
"""


def serve(profiles: list[UserProfile], repository, departments: list[Department], host: str, port: int) -> None:
    handler = _handler(profiles, repository, departments)
    server = HTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _handler(profiles: list[UserProfile], repository, departments: list[Department]):
    known = {profile.id: profile for profile in profiles}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            parsed = urlsplit(self.path)
            if (parsed.path.rstrip("/") or "/") != "/cv":
                self.send_error(404, "No such page")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > MAX_CV_BYTES + 500_000:
                self._send(_cv_error("That CV is larger than 12 MB."))
                return
            try:
                filename, data = uploaded_file(self.headers.get("Content-Type", ""), self.rfile.read(length))
                reading = read_cv(filename, data)
            except CvReadError as exc:
                self._send(_cv_error(str(exc)))
                return
            query = urlencode(
                {
                    "degree": reading.degree,
                    "field": reading.field,
                    "country": "all",
                    "from": "cv",
                    "why": reading.reason,
                }
            )
            self._redirect(f"/browse?{query}", code=303)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if path == "/":
                self._redirect("/browse?degree=all")
                return
            if path in {"/portfolio", "/portfolio/save", "/portfolio/status", "/portfolio/remove"}:
                self._portfolio(path, query, profiles, departments, repository)
                return
            field_text = " ".join((query.get("field") or query.get("department") or [""])[0].split())[:80]
            country = (query.get("country") or ["all"])[0].strip() or "all"
            degree = (query.get("degree") or ["all"])[0]
            if degree not in {"all", "phd", "masters", "bachelor"}:
                degree = "all"
            from_cv = (query.get("from") or [""])[0] == "cv"
            cv_reason = (query.get("why") or [""])[0]
            by_id = {item.id: live_matches(repository, item) for item in profiles}
            saved_ids = {item_id for item_id, _status in repository.list_portfolio()}
            if path == "/browse":
                profile = profile_for_query(field_text, degree, require_field=not from_cv)
                found = [match for match in live_matches(repository, profile) if _in_country(match, country)]
                by_id["browse"] = found
                active_id = "browse"
                department_text = field_text
            else:
                profile_id = path.lstrip("/")
                if profile_id not in known:
                    self.send_error(404, "No such person")
                    return
                profile = known[profile_id]
                active_id = profile_id
                degree = "masters" if profile.degree_levels == ["masters"] else "phd"
                department_text = ""
                country = "all"
            page = render_site(
                profiles,
                active_id,
                by_id,
                departments,
                "",
                department_text,
                degree,
                country,
                saved_ids=saved_ids,
                return_to=self.path if self.path.startswith("/") else "/browse?degree=all",
                portfolio_count=len(saved_ids),
                from_cv=from_cv,
                cv_reason=cv_reason,
            )
            self._send(page)

        def _portfolio(self, path: str, query: dict, profiles, departments, repository) -> None:
            opportunity_id = (query.get("id") or [""])[0].strip().lower()
            if path == "/portfolio/save" and _ITEM_ID.fullmatch(opportunity_id):
                if repository.get_by_id(opportunity_id) is not None:
                    repository.save_to_portfolio(opportunity_id, datetime.now(timezone.utc))
                    repository.commit()
                self._redirect(_safe_back((query.get("back") or ["/portfolio"])[0]))
                return
            if path == "/portfolio/status" and _ITEM_ID.fullmatch(opportunity_id):
                repository.set_portfolio_status(opportunity_id, (query.get("status") or [""])[0])
                repository.commit()
                self._redirect("/portfolio")
                return
            if path == "/portfolio/remove" and _ITEM_ID.fullmatch(opportunity_id):
                repository.remove_from_portfolio(opportunity_id)
                repository.commit()
                self._redirect("/portfolio")
                return
            saved = repository.list_portfolio()
            items = []
            for item_id, status in saved:
                opportunity = repository.get_by_id(item_id)
                if opportunity is not None and status in {"saved", "applying", "applied"}:
                    items.append((status, opportunity))
            by_id = {item.id: live_matches(repository, item) for item in profiles}
            page = render_portfolio(profiles, by_id, departments, items, len(saved))
            self._send(page)

        def _send(self, page: str) -> None:
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str, code: int = 302) -> None:
            self.send_response(code)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def _navigation(profiles, active_id: str, matches_by_id: dict, portfolio_count: int) -> str:
    links = [
        _nav_link(profile, active_id, len(matches_by_id.get(profile.id, []))) for profile in profiles
    ]
    browse_class = "active" if active_id == "browse" else ""
    portfolio_class = "active" if active_id == "portfolio" else ""
    links.append(f'<a class="{browse_class}" href="/browse?degree=all&country=all">Scholarships</a>')
    links.append(
        f'<a class="{portfolio_class}" href="/portfolio">Portfolio <span>{portfolio_count}</span></a>'
    )
    return "\n".join(links)


def _safe_back(value: str) -> str:
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/portfolio"


def _nav_link(profile: UserProfile, active_id: str, count: int) -> str:
    selected = "active" if profile.id == active_id else ""
    name = html.escape(profile.display_name)
    return f'<a class="{selected}" href="/{html.escape(profile.id)}">{name} <span>{count}</span></a>'


def _profile_line(profile: UserProfile) -> str:
    degrees = ", ".join(_DEGREE_LABELS.get(level, level) for level in profile.degree_levels)
    kinds = " and ".join(profile.opportunity_types) or "listings"
    places = ", ".join(profile.countries) or "worldwide"
    fields = profile.department_label or ", ".join(profile.disciplines) or "all fields"
    return f"{degrees} {kinds} · {places} · {fields}"


def _cv_error(message: str) -> str:
    return _document(
        "CV",
        '<a href="/browse?degree=all&country=all">Scholarships</a>',
        message,
        '<p><a href="/browse?degree=all&country=all">Back to scholarships</a></p>',
    )


def _search_box(country: str, department_text: str, degree: str, from_cv: bool = False, cv_reason: str = "") -> str:
    names = all_country_names()
    chosen = canonicalize_country(country) or country
    if chosen not in {"", "all"} and chosen not in names:
        names.append(chosen)
        names.sort()
    country_options = ['<option value="all">All countries</option>']
    for name in names:
        selected = " selected" if name == chosen else ""
        country_options.append(f'<option value="{html.escape(name)}"{selected}>{html.escape(name)}</option>')
    degree_options = []
    for value, label in (
        ("all", "All scholarships"),
        ("phd", "PhD"),
        ("masters", "Master's"),
        ("bachelor", "Bachelor's"),
    ):
        selected = " selected" if value == degree else ""
        degree_options.append(f'<option value="{value}"{selected}>{label}</option>')
    typed = html.escape(department_text, quote=True)
    return f"""<form class="search" action="/browse" method="get">
  <label>Country<select name="country">{"".join(country_options)}</select></label>
  <label>Department<input name="field" value="{typed}" placeholder="Computer science, law, medicine"></label>
  <label>Looking for<select name="degree">{"".join(degree_options)}</select></label>
  <button type="submit">Show scholarships</button>
</form>
<form class="search" action="/cv" method="post" enctype="multipart/form-data">
  <label>CV<input type="file" name="cv" required></label>
  <button type="submit">Search with CV</button>
</form>
<p class="note">{_cv_note(department_text, degree, from_cv, cv_reason)}</p>"""


def _cv_note(department_text: str, degree: str, from_cv: bool, cv_reason: str = "") -> str:
    if not from_cv:
        return "Type a department, or upload a CV. PDF, a photo, Word, and any other file are accepted. It is read on this computer and is not saved."
    field = department_text.strip() or "every department"
    if cv_reason == "completed-master":
        return (
            f"Your CV shows a finished master's, so these are PhD scholarships and positions in every country. "
            f"The ones that mention {html.escape(field)} are listed first. Every other open PhD listing is included."
        )
    if cv_reason == "completed-bachelor":
        return (
            f"Your CV shows a finished bachelor's, so this list is master's scholarships in {html.escape(field)}. "
            "Change Looking for if you want a different level."
        )
    level = {"phd": "PhD", "masters": "Master's", "bachelor": "Bachelor's"}.get(degree, "every degree")
    return (
        f"Read from your CV: {html.escape(level)} · {html.escape(field)}. "
        "Change the boxes if you want a different search."
    )


def _cards(matches, country, departments, department_text, saved_ids, return_to, from_cv: bool) -> tuple[str, int]:
    if not matches:
        return _empty(country, department_text), 0
    if not (from_cv and department_text.strip()):
        sections = _sections(matches, country)
        body = "\n".join(
            _section(name, group, departments, department_text, saved_ids, return_to) for name, group in sections
        )
        return body, 0
    close = [match for match in matches if _field_hit(match, department_text)]
    close_ids = {id(match) for match in close}
    rest = [match for match in matches if id(match) not in close_ids]
    parts: list[str] = []
    if close:
        parts.append(_section(f"Closest to your CV · {len(close)}", close, departments, department_text, saved_ids, return_to))
    if rest:
        parts.append(f'<h2 class="country">Every other open listing · {len(rest)}</h2>')
        parts.extend(
            _section(name, group, departments, department_text, saved_ids, return_to)
            for name, group in _sections(rest, country)
        )
    return "\n".join(parts), len(close)


def _field_hit(match: PendingMatch, field_text: str) -> bool:
    text = f"{match.opportunity.title} {match.opportunity.summary}"
    return any(term_in_text(term, text) for term in search_terms(field_text))


def _section(
    country: str,
    matches: list[PendingMatch],
    departments: list[Department],
    typed: str,
    saved_ids: set[str],
    return_to: str,
) -> str:
    cards = "\n".join(_card(match, departments, typed, saved_ids, return_to) for match in matches)
    return f'<h2 class="country">{html.escape(country)}</h2>\n{cards}'


def _sections(matches: list[PendingMatch], country: str) -> list[tuple[str, list[PendingMatch]]]:
    if country not in {"", "all"}:
        label = canonicalize_country(country) or country
        return [(label, matches)] if matches else []
    groups: dict[str, list[PendingMatch]] = {}
    for match in matches:
        groups.setdefault(_primary_country(match), []).append(match)
    ordered = sorted(name for name in groups if name != "International")
    if "International" in groups:
        ordered.append("International")
    return [(name, groups[name]) for name in ordered]


def _primary_country(match: PendingMatch) -> str:
    names = [_country_name(value) for value in match.opportunity.countries]
    names = [name for name in names if name]
    return names[0] if names else "International"


def _country_name(value: str) -> str:
    return canonicalize_country(value) or value.strip()


def _in_country(match: PendingMatch, country: str) -> bool:
    if country in {"", "all"}:
        return True
    wanted = canonicalize_country(country) or country
    return wanted in {_country_name(value) for value in match.opportunity.countries}


def _show(match: PendingMatch) -> bool:
    title = match.opportunity.title
    if _NOISE.search(title):
        return False
    if "guide" in match.opportunity.opportunity_types:
        return False
    if _NAMED.search(title):
        return True
    return bool(match.opportunity.degree_levels or match.opportunity.opportunity_types)


def _card(
    match: PendingMatch,
    departments: list[Department],
    typed: str = "",
    saved_ids: set[str] | None = None,
    return_to: str = "/browse?degree=all&country=all",
) -> str:
    item = match.opportunity
    countries = ", ".join(_country_name(value) for value in item.countries if value) or "International"
    text = f"{item.title} {item.summary}"
    degrees = _degree_line(item)
    funding = {"fully_funded": "Fully funded", "partial": "Partial funding"}.get(item.funding, "Not listed")
    deadline_date = item.deadline or extract_deadline(text)
    deadline = deadline_phrase(text) or (_written_date(deadline_date) if deadline_date else "Not published")
    opens = opening_phrase(text, deadline_date) or "Not published"
    department = _department_label(item.title, item.summary, departments, typed)
    what = html.escape(_what(item.summary))
    left = _time_left(deadline_date)
    left_html = f"<div><dt>Time left</dt><dd>{html.escape(left)}</dd></div>" if left else ""
    soon = " soon" if left in {"Closes today", "1 day left"} or left.endswith("days left") and _soon(deadline_date) else ""
    return f"""<article class="{soon.strip()}">
  <h3>{html.escape(item.title)}</h3>
  <dl>
    <div><dt>Country</dt><dd>{html.escape(countries)}</dd></div>
    <div><dt>Department</dt><dd>{html.escape(department)}</dd></div>
    <div><dt>Degree</dt><dd>{html.escape(degrees)}</dd></div>
    <div><dt>Funding</dt><dd>{html.escape(funding)}</dd></div>
    <div><dt>Opens</dt><dd>{html.escape(opens)}</dd></div>
    <div><dt>Deadline</dt><dd>{html.escape(deadline)}</dd></div>
    {left_html}
  </dl>
  <p class="summary">{what}</p>
  <p class="official"><a href="{html.escape(item.url, quote=True)}">Official page</a></p>
  {_save_control(item.id, item.id in (saved_ids or set()), return_to)}
</article>"""


def _time_left(deadline_date) -> str:
    if deadline_date is None:
        return ""
    days = (deadline_date - datetime.now(timezone.utc).date()).days
    if days < 0:
        return "Closed"
    if days == 0:
        return "Closes today"
    if days == 1:
        return "1 day left"
    return f"{days} days left"


def _soon(deadline_date) -> bool:
    if deadline_date is None:
        return False
    days = (deadline_date - datetime.now(timezone.utc).date()).days
    return 0 <= days <= 14


def _save_control(item_id: str, saved: bool, return_to: str) -> str:
    if saved:
        return '<p class="save"><a href="/portfolio">In your portfolio</a></p>'
    return (
        '<form class="save" action="/portfolio/save" method="get">'
        f'<input type="hidden" name="id" value="{html.escape(item_id, quote=True)}">'
        f'<input type="hidden" name="back" value="{html.escape(return_to, quote=True)}">'
        "<button type=\"submit\">Save to portfolio</button></form>"
    )


def render_portfolio(profiles, matches_by_id, departments, items, portfolio_count: int) -> str:
    nav = _navigation(profiles, "portfolio", matches_by_id, portfolio_count)
    columns = []
    for status, label in (("saved", "Saved"), ("applying", "Applying"), ("applied", "Applied")):
        group = [item for item_status, item in items if item_status == status]
        cards = "\n".join(_portfolio_card(item, status) for item in group) or '<p class="empty">None yet.</p>'
        columns.append(f'<section class="column"><h2>{label}</h2>{cards}</section>')
    lede = (
        "The scholarships you chose to apply for, with the days left on each one."
        if items
        else "Save a scholarship from the finder. It stays here while you prepare the application."
    )
    return _document("Portfolio", nav, lede, '<div class="board">' + "".join(columns) + "</div>")


def _portfolio_card(item, status: str) -> str:
    text = f"{item.title} {item.summary}"
    deadline_date = item.deadline or extract_deadline(text)
    deadline = deadline_phrase(text) or (_written_date(deadline_date) if deadline_date else "Not published")
    left = _time_left(deadline_date) or "No date published"
    country = ", ".join(_country_name(value) for value in item.countries if value) or "International"
    move = {
        "saved": ("applying", "Start applying"),
        "applying": ("applied", "Mark applied"),
    }.get(status)
    action = ""
    if move:
        action = (
            '<form action="/portfolio/status" method="get">'
            f'<input type="hidden" name="id" value="{html.escape(item.id, quote=True)}">'
            f'<input type="hidden" name="status" value="{move[0]}">'
            f"<button type=\"submit\">{move[1]}</button></form>"
        )
    remove = (
        '<form action="/portfolio/remove" method="get">'
        f'<input type="hidden" name="id" value="{html.escape(item.id, quote=True)}">'
        "<button type=\"submit\">Remove</button></form>"
    )
    return f"""<article>
  <h3>{html.escape(item.title)}</h3>
  <dl>
    <div><dt>Country</dt><dd>{html.escape(country)}</dd></div>
    <div><dt>Degree</dt><dd>{html.escape(_degree_line(item))}</dd></div>
    <div><dt>Deadline</dt><dd>{html.escape(deadline)}</dd></div>
    <div><dt>Time left</dt><dd>{html.escape(left)}</dd></div>
  </dl>
  <div class="actions">{action}{remove}</div>
  <p class="official"><a href="{html.escape(item.url, quote=True)}">Official page</a></p>
</article>"""


def _written_date(value) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def _mentioned_degrees(text: str) -> list[str]:
    found: list[str] = []
    if re.search(r"\b(?:bachelors?|undergraduates?)\b", text, re.IGNORECASE):
        found.append("Bachelor's")
    if re.search(r"\b(?:masters?|postgraduates?|m\.?\s?sc\.?|mba)\b", text, re.IGNORECASE):
        found.append("Master's")
    if re.search(r"\b(?:ph\.?\s*d\.?|doctoral|first stage researcher)\b|\(R1\)", text, re.IGNORECASE):
        found.append("PhD")
    return found


def _degree_line(item) -> str:
    titled = _mentioned_degrees(item.title)
    if titled:
        return ", ".join(titled)
    prose = re.sub(
        r"\bDegree:\s*(?:PhD|Master's|Bachelor's)(?:\s*,\s*(?:PhD|Master's|Bachelor's))*\.\s*",
        "",
        item.summary,
        count=1,
    )
    found = _mentioned_degrees(prose)
    if not found and re.search(r"\bgraduates?\b", prose, re.IGNORECASE):
        return "Master's, PhD"
    if found:
        return ", ".join(found)
    if item.degree_levels:
        labels = [
            _DEGREE_LABELS.get(level, level)
            for level in item.degree_levels
            if level in _DEGREE_LABELS
        ]
        if labels:
            return ", ".join(labels)
    if re.search(r"\bany degree\b|\ball degree levels\b|\ball levels\b", f"{item.title} {prose}", re.IGNORECASE):
        return "Bachelor's, Master's, PhD"
    return "Any degree"


def _trim_field(phrase: str) -> str:
    piece = re.split(r"\s+(?:for|at|in|to|with|,|\|)\s+", phrase, maxsplit=1, flags=re.IGNORECASE)[0]
    piece = re.split(r"\s*\(", piece, maxsplit=1)[0]
    words: list[str] = []
    for word in piece.split():
        if canonicalize_country(word):
            break
        words.append(word)
    cleaned = " ".join(words).strip(" -–|")
    if (
        len(cleaned) < 3
        or cleaned.lower() in _GENERIC_FIELD
        or canonicalize_country(cleaned)
        or re.match(r"^(?:any|all|every)\b", cleaned, re.IGNORECASE)
    ):
        return ""
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned[:1].upper() + cleaned[1:]


def _remember(found: list[str], phrase: str) -> None:
    cleaned = _trim_field(phrase)
    if cleaned and cleaned not in found:
        found.append(cleaned)


def _department_label(title: str, summary: str, departments: list[Department], typed: str = "") -> str:
    text = f"{title} {summary}"
    found: list[str] = []
    for pattern in (_FACULTY, _AREA, _CENTRE, _PROGRAMME):
        for phrase in pattern.findall(text):
            _remember(found, phrase)
    for word, label in _FIELD_WORDS:
        if term_in_text(word, text) and label not in found:
            found.append(label)
    for department in departments:
        if not department.keywords or department.id == "any":
            continue
        if any(term_in_text(keyword, text) for keyword in department.keywords) and department.label not in found:
            found.append(department.label)
    for word in typed.replace(",", " ").split():
        if term_in_text(word, text) and word.lower() not in {label.lower() for label in found}:
            found.append(word[:1].upper() + word[1:])
    if found:
        return ", ".join(found[:3])
    if re.search(r"science and technology|scientific and technological", text, re.IGNORECASE):
        return "Science and technology"
    if _OPEN_DEPARTMENT.search(text):
        return "All departments"
    return "Not named in the notice"


def _what(summary: str) -> str:
    text = re.sub(
        r"\bDegree:\s*(?:PhD|Master's|Bachelor's)(?:\s*,\s*(?:PhD|Master's|Bachelor's))*\.\s*",
        "",
        summary,
        count=1,
    )
    text = re.sub(r"the post .+ first appeared on .+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bread more\b.*$", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    if not text:
        return "The public excerpt does not describe this scholarship."
    if len(text) > 360:
        return text[:359].rsplit(" ", 1)[0] + "…"
    return text


def _empty(country: str, department: str) -> str:
    place = "these filters" if country in {"", "all"} and not department else " ".join(
        part for part in (country if country not in {"", "all"} else "", department) if part
    )
    return (
        f'<p class="empty">No scholarship states {html.escape(place or "that combination")}. '
        'Choose another country or <a href="/browse?degree=all&country=all">show every country</a>.</p>'
    )
