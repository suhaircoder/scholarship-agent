"""Wire configuration, storage, feeds, and delivery into one runtime."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from scholarship_agent.agent import OpportunityAgent
from scholarship_agent.channels import (
    EmailDistributor,
    FileDistributor,
    LogDistributor,
    TelegramDistributor,
)
from scholarship_agent.enrich import NoopEnricher, OpenAICompatibleEnricher
from scholarship_agent.euraxess import EuraxessSearchScraper
from scholarship_agent.wordpress import WordPressPostScraper
from scholarship_agent.http_client import HttpFetcher
from scholarship_agent.profiles import (
    Settings,
    SourceConfig,
    UserProfile,
    load_departments,
    load_profiles,
    load_settings,
    load_sources,
)
from scholarship_agent.rss import RssScraper, ScraperRegistry
from scholarship_agent.storage import Repository

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    root: Path
    settings: Settings
    profiles: list[UserProfile]
    departments: list
    sources: list[SourceConfig]
    repository: Repository
    fetcher: HttpFetcher
    agent: OpportunityAgent
    enricher: object
    distributors: list

    def close(self) -> None:
        self.fetcher.close()
        closer = getattr(self.enricher, "close", None)
        if closer:
            closer()
        for distributor in self.distributors:
            closer = getattr(distributor, "close", None)
            if closer and getattr(distributor, "name", "") == "telegram":
                closer()
        self.repository.close()


def load_runtime(config_path: Path) -> Runtime:
    config_path = config_path.resolve()
    root = config_path.parent.parent
    load_dotenv(root / ".env")
    _, settings = load_settings(config_path)
    profiles = load_profiles(config_path.parent)
    departments = load_departments(config_path.parent)
    sources = load_sources(config_path.parent)
    repository = Repository(settings.database_path)
    fetcher = HttpFetcher(
        cache=repository,
        timeout=settings.http.timeout_seconds,
        max_retries=settings.http.max_retries,
        user_agent=settings.http.user_agent,
        backoff_seconds=settings.http.delay_seconds,
    )
    registry = ScraperRegistry(
        RssScraper(fetcher, settings.http.max_items_per_source),
        delay_seconds=settings.http.delay_seconds,
        euraxess=EuraxessSearchScraper(fetcher, settings.http.delay_seconds),
        wordpress=WordPressPostScraper(fetcher, settings.http.delay_seconds),
    )
    enricher = _enricher(settings)
    distributors = _distributors(settings)
    for profile in profiles:
        if not any(distributor.handles(profile) for distributor in distributors):
            logger.warning("%s has no delivery channel configured", profile.display_name)
    agent = OpportunityAgent(
        settings=settings,
        profiles=profiles,
        sources=sources,
        repository=repository,
        scrapers=registry,
        enricher=enricher,
        distributors=distributors,
    )
    return Runtime(
        root=root,
        settings=settings,
        profiles=profiles,
        sources=sources,
        repository=repository,
        fetcher=fetcher,
        agent=agent,
        enricher=enricher,
        distributors=distributors,
        departments=departments,
    )


def _enricher(settings: Settings):
    if not settings.llm.enabled:
        return NoopEnricher()
    api_key = os.getenv(settings.llm.api_key_env, "").strip()
    if not api_key:
        logger.warning(
            "LLM classification is enabled but %s is empty. The built-in rules will be used.",
            settings.llm.api_key_env,
        )
        return NoopEnricher()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or settings.llm.base_url
    return OpenAICompatibleEnricher(
        base_url=base_url,
        api_key=api_key,
        model=settings.llm.model,
        timeout=settings.llm.timeout_seconds,
    )


def _distributors(settings: Settings) -> list:
    channels: list = []
    if settings.delivery.write_digest_files:
        channels.append(FileDistributor(settings.digests_dir))
    if settings.delivery.email.enabled:
        channels.append(EmailDistributor(settings.delivery.email))
    if settings.delivery.telegram.enabled:
        token = os.getenv(settings.delivery.telegram.bot_token_env, "").strip()
        if token:
            channels.append(TelegramDistributor(token))
        else:
            logger.warning(
                "Telegram delivery is enabled but %s is empty.",
                settings.delivery.telegram.bot_token_env,
            )
    if not channels:
        channels.append(LogDistributor())
    return channels
