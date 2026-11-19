"""Turn a feed entry into degree, funding, country, and listing type."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from dateutil import parser as date_parser

from scholarship_agent.locations import detect_countries
from scholarship_agent.models import RawItem
from scholarship_agent.textutil import clean_text

_STRONG_PHD = re.compile(
    r"\bph\.?\s*d\.?\b.{0,48}\b(positions?|students?|candidates?|scholarships?|studentships?|"
    r"openings?|vacancies|programs?|programmes?|fellowships?|grants?)\b"
    r"|\b(positions?|studentships?|scholarships?|vacancies|openings?)\b.{0,48}\bph\.?\s*d\.?\b"
    r"|\b(doctoral|doctorate|dphil)\b.{0,48}\b(positions?|students?|candidates?|scholarships?|"
    r"programs?|programmes?|fellowships?|openings?|vacancies)\b"
    r"|\bfully[- ]funded ph\.?\s*d\.?\b"
    r"|\bph\.?\s*d\.?\b\s+in\b"
    r"|\bdoktorand\w*\b"
    r"|\bpromotionsstelle\b",
    re.IGNORECASE | re.DOTALL,
)
_PREDOCTORAL = re.compile(r"\bpre-?doctoral\b", re.IGNORECASE)
_NON_DOCTORAL = re.compile(r"\bnon-?doctoral\b", re.IGNORECASE)
_PHD_RESEARCHER = re.compile(
    r"\bph\.?\s*d\.?\s+researchers?\b|\bresearchers?\b.{0,24}\bph\.?\s*d\.?\b",
    re.IGNORECASE | re.DOTALL,
)
_POSTDOC = re.compile(r"\bpost-?\s?docs?\b|\bpostdoctoral\b", re.IGNORECASE)
_FACULTY = re.compile(
    r"\b(?:assistant|associate|full|senior)?\s*professors?\b|\b(?:senior\s+)?lecturers?\b",
    re.IGNORECASE,
)
_MASTERS = re.compile(
    r"\bmasters?\b|\bm\.?\s?sc\.?\b|\bmba\b|\bmphil\b|\bpostgraduates?\b",
    re.IGNORECASE,
)
_BACHELOR = re.compile(r"\bbachelors?\b|\bundergraduate\b|\bb\.?\s?sc\.?\b", re.IGNORECASE)
_SCHOLARSHIP = re.compile(r"\bscholarships?\b|\bbursar(?:y|ies)\b|\bstipends?\b", re.IGNORECASE)
_FELLOWSHIP = re.compile(r"\bfellowships?\b", re.IGNORECASE)
_POSITION = re.compile(
    r"\b(positions?|studentships?|vacancies|openings?|phd students?)\b",
    re.IGNORECASE,
)
_GUIDE = re.compile(
    r"\bhow to\b|\bpractical steps\b|\buniversities\b.{0,80}\boffering\b|"
    r"\b\d+\s+universities\b|\bguide to\b|\bthings you need\b",
    re.IGNORECASE | re.DOTALL,
)
_LISTICLE = re.compile(
    r"\b(?:top\s+)?\d+\+?\s+(?:best|top|universities|scholarships|international|fully)\b|"
    r"\btop\s+\d+\b|\btop\b.{0,40}\bscholarships\b",
    re.IGNORECASE | re.DOTALL,
)
_FULLY_FUNDED = re.compile(
    r"\bfully[- ]funded\b|\bfull scholarship\b|\bfull tuition\b",
    re.IGNORECASE,
)
_PARTIAL = re.compile(r"\bpartial(?:ly)?[- ]funded\b|\btuition waiver\b|\bfee waiver\b", re.IGNORECASE)
_MONTH = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_TOKEN = (
    rf"\d{{1,2}}(?:st|nd|rd|th)?(?:\s+of)?\s+(?:{_MONTH})\s+20\d{{2}}"
    rf"|(?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+20\d{{2}}"
    rf"|\d{{1,2}}[./]\d{{1,2}}[./]20\d{{2}}"
    rf"|20\d{{2}}-\d{{2}}-\d{{2}}"
)
_DEADLINE = re.compile(
    rf"(?:application\s+)?(?:deadline|closing date|apply by|applications close|due date).{{0,48}}?"
    rf"({_DATE_TOKEN})",
    re.IGNORECASE,
)
_DEADLINE_STATUS = re.compile(
    r"(?:application\s+)?deadline\s*[:\-–]?\s*"
    r"(open all year|all year|ongoing|rolling(?:\s+basis)?|"
    r"varies(?:\s+by\s+(?:institution|university))?|to be announced|tba|not specified)",
    re.IGNORECASE,
)
_CLOCK = re.compile(
    rf"({_DATE_TOKEN})\s*[-–]\s*(\d{{1,2}}:\d{{2}})(?:\s*\(([^)]{{2,48}})\))?",
    re.IGNORECASE,
)
_OPEN_NOW = re.compile(
    r"\bapplications?\s+(?:are\s+)?(?:currently\s+|now\s+)?open\b"
    r"|\bapplication\s+is\s+(?:currently\s+|now\s+)?open\b",
    re.IGNORECASE,
)
_OPEN_DATE = re.compile(
    rf"(?:applications?\s+open(?:s|ed)?|opening date|apply from|opens?\s+on)\s*[:\-–]?\s*({_DATE_TOKEN})",
    re.IGNORECASE,
)
_META_CATEGORY = re.compile(
    r"scholarship|fellowship|study abroad|blog|fully funded|full scholarship|funded|advice|news",
    re.IGNORECASE,
)
_GUIDE_CATEGORIES = {"blog", "study abroad", "career advice", "news"}


@dataclass
class Classification:
    degree_levels: list[str] = field(default_factory=list)
    opportunity_types: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    funding: str = "unknown"
    deadline: date | None = None
    confidence: float = 0.35
    is_actionable: bool = True


def _levels(text: str) -> set[str]:
    found: set[str] = set()
    if _POSTDOC.search(text):
        found.add("postdoc")
    searchable = _NON_DOCTORAL.sub(" ", text)
    strong_phd = _STRONG_PHD.search(searchable) is not None
    if _FACULTY.search(text) and not strong_phd:
        found.add("faculty")
    if strong_phd or (_PREDOCTORAL.search(text) and not _NON_DOCTORAL.search(text)):
        found.add("phd")
    elif _PHD_RESEARCHER.search(text):
        found.add("researcher")
    if _MASTERS.search(text) and "faculty" not in found:
        found.add("masters")
    if re.search(r"\bfirst stage researcher\b|\(R1\)", text, re.IGNORECASE):
        found.add("phd")
    if re.search(r"\bdegree:\s*[^.]{0,80}\bph\.?\s*d\.?\b", text, re.IGNORECASE):
        found.add("phd")
    if re.search(r"\brecognised researcher\b|\(R2\)", text, re.IGNORECASE) and "phd" not in found:
        found.add("postdoc")
    if _BACHELOR.search(text) and not (found & {"phd", "masters", "postdoc"}):
        found.add("bachelor")
    elif re.search(r"\b(?:bachelors?|undergraduates?)\b", text, re.IGNORECASE):
        found.add("bachelor")
    return found


def _types(text: str) -> set[str]:
    found: set[str] = set()
    if _SCHOLARSHIP.search(text):
        found.add("scholarship")
    if _FELLOWSHIP.search(text):
        found.add("fellowship")
        found.add("scholarship")
    if _POSITION.search(text) or _PHD_RESEARCHER.search(text) or _FACULTY.search(text):
        found.add("position")
    return found


def _funding(text: str) -> str:
    if _FULLY_FUNDED.search(text) or (_PARTIAL.search(text) and re.search(r"\bstipend\b", text, re.I)):
        return "fully_funded"
    if _PARTIAL.search(text):
        return "partial"
    return "unknown"


def format_when(value: date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def _parse_when(raw: str) -> date | None:
    cleaned = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bof\b", " ", cleaned, flags=re.IGNORECASE)
    try:
        parsed = date_parser.parse(cleaned, dayfirst=True, fuzzy=False)
    except (ValueError, OverflowError):
        return None
    if parsed.year < 2000 or parsed.year > 2100:
        return None
    return parsed.date()


def extract_deadline(text: str) -> date | None:
    match = _DEADLINE.search(text)
    if not match:
        return None
    return _parse_when(match.group(1))


def deadline_phrase(text: str) -> str:
    """The deadline as a reader should see it, including a clock time when the notice gives one."""
    found = extract_deadline(text)
    if found:
        phrase = format_when(found)
        for clock in _CLOCK.finditer(text):
            if _parse_when(clock.group(1)) != found:
                continue
            zone = f" ({clock.group(3).strip()})" if clock.group(3) else ""
            return f"{phrase}, {clock.group(2)}{zone}"
        return phrase
    status = _DEADLINE_STATUS.search(text)
    if not status:
        return ""
    return _status_label(status.group(1))


def opening_phrase(text: str, deadline: date | None = None, today: date | None = None) -> str:
    """When applications open. A published call with a future deadline is open now."""
    today = today or date.today()
    dated = _OPEN_DATE.search(text)
    if dated:
        parsed = _parse_when(dated.group(1))
        if parsed:
            return format_when(parsed)
    status = deadline_phrase(text)
    if status in {"Open all year", "Varies by institution", "To be announced"}:
        return status
    if _OPEN_NOW.search(text) or status == "Rolling":
        return "Open now"
    if deadline and deadline >= today:
        return "Open now"
    return ""


def schedule_notes(text: str) -> str:
    """Keep the opening, deadline, and degree lines. Leave the rest of the article behind."""
    if not text.strip():
        return ""
    pieces: list[str] = []
    deadline = _DEADLINE.search(text)
    status = _DEADLINE_STATUS.search(text)
    if deadline:
        clock = _CLOCK.search(text[deadline.start() : deadline.start() + 96])
        if clock and clock.group(3):
            pieces.append(f"Deadline: {clock.group(1)} - {clock.group(2)} ({clock.group(3).strip()}).")
        elif clock:
            pieces.append(f"Deadline: {clock.group(1)} - {clock.group(2)}.")
        else:
            pieces.append(f"Deadline: {deadline.group(1)}.")
    elif status:
        pieces.append(status.group(0).strip(" .") + ".")
    if _OPEN_NOW.search(text):
        pieces.append("Applications are currently open.")
    else:
        opened = _OPEN_DATE.search(text)
        if opened:
            parsed = _parse_when(opened.group(1))
            if parsed:
                pieces.append(f"Applications open {format_when(parsed)}.")
    eligible = _eligibility_sentence(text[:1800])
    if eligible:
        pieces.append(eligible)
    unique: list[str] = []
    for piece in pieces:
        if piece not in unique:
            unique.append(piece)
    return " ".join(unique)[:500]


def _eligibility_sentence(text: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(sentence) < 20:
            continue
        if not re.search(
            r"\b(?:bachelors?|undergraduates?|masters?|postgraduates?|ph\.?\s*d\.?|doctoral)\b",
            sentence,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\b(?:not|except|excluding)\b.{0,30}\b(?:bachelor|master|ph\.?\s*d|undergraduate|postgraduate)",
            sentence,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\b(?:scholarship|eligible|open to|pursue|applicants?|students?|programmes?|programs?|degree|study|fellowship)\b",
            sentence,
            re.IGNORECASE,
        ):
            return sentence.strip()[:300]
    return ""


def _without_generated_degree(text: str) -> str:
    return re.sub(
        r"\bDegree:\s*(?:PhD|Master's|Bachelor's)(?:\s*,\s*(?:PhD|Master's|Bachelor's))*\.\s*",
        "",
        text,
        count=1,
    )


def _status_label(raw: str) -> str:
    text = " ".join(raw.split()).lower()
    if "varies" in text:
        return "Varies by institution"
    if "all year" in text:
        return "Open all year"
    if "ongoing" in text or "rolling" in text:
        return "Rolling"
    if "not specified" in text:
        return "Not specified"
    if "announce" in text or text == "tba":
        return "To be announced"
    return "Not dated"


def _deadline(text: str) -> date | None:
    return extract_deadline(text)


def _fields(categories: list[str]) -> list[str]:
    fields: list[str] = []
    for category in categories:
        cleaned = clean_text(category, limit=80)
        if not cleaned or _META_CATEGORY.search(cleaned):
            continue
        if cleaned not in fields:
            fields.append(cleaned)
    return fields


def _is_guide(title: str, categories: list[str]) -> bool:
    named_award = re.search(r"\b(?:scholarships?|fellowships?|studentships?)\b", title, re.IGNORECASE)
    if _LISTICLE.search(title):
        return True
    if named_award:
        return False
    if _GUIDE.search(title):
        return True
    names = {clean_text(category, limit=80).lower() for category in categories}
    return bool(names & _GUIDE_CATEGORIES)


def classify_text(title: str, summary: str = "", categories: list[str] | None = None) -> Classification:
    categories = categories or []
    title = clean_text(title, limit=400)
    summary = _without_generated_degree(clean_text(summary))
    category_text = " ".join(clean_text(category, limit=80) for category in categories)
    heading = f"{title} {category_text}".strip()
    title_levels = _levels(heading)
    body_levels = _levels(summary)
    student_levels = {"phd", "masters", "bachelor", "postdoc"}

    if title_levels & {"faculty", "researcher"} and not (title_levels & student_levels):
        degrees = title_levels
        degree_source = "title"
    elif title_levels & student_levels:
        degrees = {level for level in title_levels if level != "faculty"}
        degree_source = "title"
    elif body_levels:
        degrees = body_levels
        degree_source = "body"
    else:
        degrees = set()
        degree_source = "none"

    heading_types = _types(heading)
    body_types = _types(summary)
    types = heading_types or body_types
    if "faculty" in degrees or "researcher" in degrees or "postdoc" in degrees:
        types.add("position")

    if "phd" in degrees and not (types & {"position", "scholarship"}):
        types.add("position")

    guide = _is_guide(title, categories)
    if guide:
        types.add("guide")

    joined = f"{heading} {summary}"
    funding = _funding(joined)
    countries = detect_countries(title, category_text, summary)
    fields = _fields(categories)
    actionable = not guide

    if guide:
        confidence = 0.9
    elif degree_source == "title" and "phd" in degrees and types:
        confidence = 0.92
    elif degree_source == "title" and degrees & {"masters", "bachelor", "faculty", "postdoc"} and types:
        confidence = 0.9
    elif "researcher" in degrees:
        confidence = 0.7
    elif degree_source == "body" and degrees:
        confidence = 0.62
    elif types:
        confidence = 0.5
    else:
        confidence = 0.35

    return Classification(
        degree_levels=sorted(degrees),
        opportunity_types=sorted(types),
        countries=countries,
        fields=fields,
        funding=funding,
        deadline=_deadline(joined),
        confidence=confidence,
        is_actionable=actionable,
    )


def classify_item(item: RawItem) -> Classification:
    return classify_text(item.title, item.summary, item.categories)

