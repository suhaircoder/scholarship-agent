"""Load settings, sources, and the two user profiles."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from scholarship_agent.errors import ConfigError

ALLOWED_DEGREES = {"phd", "masters", "bachelor", "postdoc", "researcher", "faculty"}
ALLOWED_TYPES = {"position", "scholarship", "fellowship", "guide"}
ALLOWED_FUNDING = {"fully_funded", "partial", "unknown"}


class HttpSettings(BaseModel):
    timeout_seconds: float = 30
    max_retries: int = 3
    delay_seconds: float = 1.5
    user_agent: str = "ScholarshipAgent/0.1 (personal academic digest; public RSS only)"
    max_items_per_source: int = 40


class LlmSettings(BaseModel):
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 45
    max_items_per_run: int = 20
    confidence_below: float = 0.8


class EmailSettings(BaseModel):
    enabled: bool = False
    host_env: str = "SMTP_HOST"
    port_env: str = "SMTP_PORT"
    username_env: str = "SMTP_USERNAME"
    password_env: str = "SMTP_PASSWORD"
    from_env: str = "SMTP_FROM"
    use_tls: bool = True


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"


class DeliverySettings(BaseModel):
    write_digest_files: bool = True
    email: EmailSettings = Field(default_factory=EmailSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)


class ScheduleSettings(BaseModel):
    interval_hours: float = 2


class Settings(BaseModel):
    database_path: Path = Path("data/opportunities.db")
    digests_dir: Path = Path("data/digests")
    log_dir: Path = Path("data/logs")
    http: HttpSettings = Field(default_factory=HttpSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)


class SourceConfig(BaseModel):
    id: str
    type: str = "rss"
    url: str
    enabled: bool = True
    description: str = ""
    pages: int = 1


class Department(BaseModel):
    id: str
    label: str
    keywords: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    id: str
    display_name: str
    degree_levels: list[str]
    opportunity_types: list[str]
    countries: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    keywords_include: list[str] = Field(default_factory=list)
    keywords_exclude: list[str] = Field(default_factory=list)
    funding_preference: list[str] = Field(
        default_factory=lambda: ["fully_funded", "partial", "unknown"]
    )
    allow_unknown_funding: bool = True
    require_discipline_match: bool = True
    min_score: float = 60
    department: str = ""
    department_label: str = ""
    email: str = ""
    email_env: str = ""
    telegram_chat_id: str = ""
    telegram_chat_id_env: str = ""

    @property
    def resolved_email(self) -> str:
        if self.email_env:
            value = os.getenv(self.email_env, "").strip()
            if value:
                return value
        return self.email.strip()

    @property
    def resolved_telegram_chat_id(self) -> str:
        if self.telegram_chat_id_env:
            value = os.getenv(self.telegram_chat_id_env, "").strip()
            if value:
                return value
        return self.telegram_chat_id.strip()


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Missing configuration file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a mapping")
    return loaded


def _clean_terms(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = " ".join(str(value).replace("\u2019", "'").split())
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def load_settings(path: Path) -> tuple[Path, Settings]:
    config_path = path.resolve()
    raw = _read_yaml(config_path)
    settings = Settings.model_validate(raw)
    root = config_path.parent.parent
    settings = settings.model_copy(
        update={
            "database_path": _resolve(root, settings.database_path),
            "digests_dir": _resolve(root, settings.digests_dir),
            "log_dir": _resolve(root, settings.log_dir),
        }
    )
    return root, settings


def load_sources(config_dir: Path) -> list[SourceConfig]:
    raw = _read_yaml(config_dir / "sources.yaml")
    entries = raw.get("sources", [])
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{config_dir / 'sources.yaml'} needs a sources list")
    sources: list[SourceConfig] = []
    seen: set[str] = set()
    for entry in entries:
        source = SourceConfig.model_validate(entry)
        if source.id in seen:
            raise ConfigError(f"Duplicate source id '{source.id}'")
        if source.type not in {"rss", "euraxess_search", "wp_posts"}:
            raise ConfigError(f"{source.id}: unsupported source type '{source.type}'")
        if source.pages < 1 or source.pages > 40:
            raise ConfigError(f"{source.id}: pages must be from 1 to 40")
        if not source.url.startswith(("https://", "http://")):
            raise ConfigError(f"{source.id}: url must start with http:// or https://")
        seen.add(source.id)
        sources.append(source)
    return sources


def load_departments(config_dir: Path) -> list[Department]:
    path = config_dir / "departments.yaml"
    raw = _read_yaml(path)
    entries = raw.get("departments", [])
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path} needs a departments list")
    departments: list[Department] = []
    seen: set[str] = set()
    for entry in entries:
        department = Department.model_validate(entry)
        department = department.model_copy(
            update={"keywords": [item.lower() for item in _clean_terms(department.keywords)]}
        )
        if department.id in seen:
            raise ConfigError(f"Duplicate department id '{department.id}'")
        seen.add(department.id)
        departments.append(department)
    return departments


_QUERY_ALIASES = {
    "saudia": ["saudi", "saudi arabia"],
    "saudi": ["saudi arabia"],
    "ksa": ["saudi", "saudi arabia"],
    "turkey": ["türkiye", "turkiye", "turkish", "istanbul"],
    "turkiye": ["turkey", "türkiye", "turkish"],
    "türkiye": ["turkey", "turkish"],
    "turkish": ["turkey", "türkiye"],
    "italy": ["italian", "italia"],
    "italian": ["italy", "italia"],
    "italia": ["italy", "italian"],
    "china": ["chinese"],
    "chinese": ["china"],
}


SEARCH_PHRASES = (
    "computer science",
    "software engineering",
    "machine learning",
    "artificial intelligence",
    "data science",
    "civil engineering",
    "mechanical engineering",
    "electrical engineering",
    "chemical engineering",
    "molecular biology",
    "public health",
)


def search_terms(department_text: str) -> list[str]:
    """Keep a department phrase together, then match any leftover word."""
    remaining = department_text.lower()
    found: list[str] = []
    for phrase in sorted(SEARCH_PHRASES, key=len, reverse=True):
        if phrase in remaining and phrase not in found:
            found.append(phrase)
            remaining = remaining.replace(phrase, " ")
    for word in remaining.replace(",", " ").split():
        if not word or word in found:
            continue
        found.append(word)
        for extra in _QUERY_ALIASES.get(word, []):
            if extra not in found:
                found.append(extra)
    return found


def profile_for_query(
    department_text: str,
    degree: str,
    keywords: list[str] | None = None,
    *,
    require_field: bool = True,
) -> UserProfile:
    """A temporary search. Blank keywords keep every field."""
    if keywords is None:
        expanded = search_terms(department_text)
    else:
        expanded = [word.lower() for word in keywords if word.strip()]
    if degree == "masters":
        levels = ["masters"]
        types = ["scholarship"]
        label = "Master's scholarships"
    elif degree == "phd":
        levels = ["phd"]
        types = ["position", "scholarship"]
        label = "PhD scholarships"
    elif degree == "bachelor":
        levels = ["bachelor"]
        types = ["scholarship"]
        label = "Bachelor's scholarships"
    else:
        levels = ["phd", "masters", "bachelor"]
        types = ["position", "scholarship", "fellowship"]
        label = "All scholarships"
    typed = department_text.strip()
    return UserProfile(
        id="browse",
        display_name=label,
        degree_levels=levels,
        opportunity_types=types,
        disciplines=expanded,
        require_discipline_match=bool(expanded) and require_field,
        department_label=typed,
    )


def profile_for_search(department: Department, degree: str) -> UserProfile:
    if degree == "masters":
        levels = ["masters"]
        types = ["scholarship"]
    else:
        levels = ["phd"]
        types = ["position", "scholarship"]
    return UserProfile(
        id="browse",
        display_name=department.label,
        degree_levels=levels,
        opportunity_types=types,
        disciplines=list(department.keywords),
        require_discipline_match=bool(department.keywords),
        department=department.id,
        department_label=department.label,
    )


def load_profiles(config_dir: Path, departments: list[Department] | None = None) -> list[UserProfile]:
    if departments is None:
        departments = load_departments(config_dir)
    by_id = {item.id: item for item in departments}
    users_dir = config_dir / "users"
    if not users_dir.is_dir():
        raise ConfigError(f"Missing profiles directory: {users_dir}")
    paths = sorted(users_dir.glob("*.yaml"))
    if not paths:
        raise ConfigError(f"No profiles in {users_dir}")
    profiles: list[UserProfile] = []
    seen: set[str] = set()
    for path in paths:
        profile = UserProfile.model_validate(_read_yaml(path))
        profile = profile.model_copy(
            update={
                "degree_levels": [item.lower() for item in _clean_terms(profile.degree_levels)],
                "opportunity_types": [item.lower() for item in _clean_terms(profile.opportunity_types)],
                "countries": _clean_terms(profile.countries),
                "disciplines": [item.lower() for item in _clean_terms(profile.disciplines)],
                "keywords_include": [item.lower() for item in _clean_terms(profile.keywords_include)],
                "keywords_exclude": [item.lower() for item in _clean_terms(profile.keywords_exclude)],
                "funding_preference": [item.lower() for item in _clean_terms(profile.funding_preference)],
                "department": profile.department.strip().lower(),
            }
        )
        if profile.department:
            department = by_id.get(profile.department)
            if department is None:
                raise ConfigError(f"{path.name}: unknown department '{profile.department}'")
            profile = profile.model_copy(
                update={
                    "department_label": department.label,
                    "disciplines": profile.disciplines or list(department.keywords),
                    "require_discipline_match": bool(profile.disciplines or department.keywords),
                }
            )
        if profile.id in seen:
            raise ConfigError(f"Duplicate profile id '{profile.id}'")
        unknown_degrees = set(profile.degree_levels) - ALLOWED_DEGREES
        unknown_types = set(profile.opportunity_types) - ALLOWED_TYPES
        unknown_funding = set(profile.funding_preference) - ALLOWED_FUNDING
        if unknown_degrees or unknown_types or unknown_funding or not profile.degree_levels:
            raise ConfigError(
                f"{path.name}: check degree_levels {sorted(unknown_degrees)}, "
                f"opportunity_types {sorted(unknown_types)}, "
                f"funding_preference {sorted(unknown_funding)}"
            )
        seen.add(profile.id)
        profiles.append(profile)
    return profiles
