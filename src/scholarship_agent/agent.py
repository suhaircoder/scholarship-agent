"""Orchestrate collection, matching, and delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from scholarship_agent.enrich import NoopEnricher
from scholarship_agent.errors import DeliveryError, EnrichmentError, SourceFetchError
from scholarship_agent.models import Digest, DigestItem, PendingMatch, RawItem
from scholarship_agent.prepare import prepare_opportunity
from scholarship_agent.profiles import Settings, SourceConfig, UserProfile
from scholarship_agent.score import score_opportunity
from scholarship_agent.storage import Repository
from scholarship_agent.textutil import is_distinctive_title

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    sources_ok: int
    source_errors: list[str]
    fetched: int
    changed: int
    previews: list[str]
    delivered: int


@dataclass
class OpportunityAgent:
    settings: Settings
    profiles: list[UserProfile]
    sources: list[SourceConfig]
    repository: Repository
    scrapers: object
    enricher: object = field(default_factory=NoopEnricher)
    distributors: list = field(default_factory=list)
    clock: object = field(default=lambda: datetime.now(timezone.utc))

    def run(self, dry_run: bool = False) -> RunReport:
        started = self._now()
        self._refresh_stored(started)
        fetched, changed, sources_ok, errors = self._ingest(started)
        self._score(started)
        previews = self._previews()
        delivered = 0
        if dry_run:
            self.repository.rollback()
            finished = self._now()
            return self._report(
                started, finished, True, sources_ok, errors, fetched, changed, previews, delivered
            )
        self.repository.commit()
        for profile in self.profiles:
            delivered += self._deliver(profile, self._now())
            self.repository.commit()
        finished = self._now()
        self.repository.add_run(
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            dry_run=False,
            sources_ok=sources_ok,
            sources_failed=len(errors),
            fetched=fetched,
            changed=changed,
            delivered=delivered,
            errors="\n".join(errors),
        )
        self.repository.commit()
        return self._report(
            started, finished, False, sources_ok, errors, fetched, changed, previews, delivered
        )

    def check(self) -> list[tuple[str, int, str | None]]:
        results: list[tuple[str, int, str | None]] = []
        for source in self.sources:
            if not source.enabled:
                continue
            try:
                items = self.scrapers.fetch(source)
            except Exception as exc:
                logger.warning("Check failed for %s: %s", source.id, exc)
                results.append((source.id, 0, str(exc)))
                continue
            results.append((source.id, len(items), None))
        # A check must not remember feed validators. Otherwise the next real run
        # hears "not modified" and never stores the listings it has not seen.
        self.repository.rollback()
        return results

    def _refresh_stored(self, now: datetime) -> None:
        for existing in self.repository.list_opportunities():
            fresh = prepare_opportunity(
                RawItem(
                    source_id=existing.source_id,
                    title=existing.title,
                    url=existing.url,
                    summary=existing.summary,
                    organization=existing.organization,
                    published_at=existing.published_at,
                ),
                now,
            )
            fresh = fresh.model_copy(
                update={
                    "duplicate_of": existing.duplicate_of,
                    "ai_summary": existing.ai_summary,
                    "enriched": existing.enriched,
                    "fetched_at": existing.fetched_at,
                }
            )
            if _same_classification(existing, fresh):
                continue
            self.repository.upsert_opportunity(fresh)

    def _ingest(self, now: datetime) -> tuple[int, int, int, list[str]]:
        fetched = 0
        changed = 0
        sources_ok = 0
        errors: list[str] = []
        budget = self.settings.llm.max_items_per_run
        for source in self.sources:
            if not source.enabled:
                continue
            try:
                items = self.scrapers.fetch(source)
                if not items and self.repository.count_by_source(source.id) == 0:
                    logger.info("%s has no stored listings yet; reading the full feed", source.id)
                    items = self.scrapers.fetch(source, conditional=False)
            except SourceFetchError as exc:
                errors.append(str(exc))
                logger.warning("%s", exc)
                continue
            except Exception as exc:
                message = f"{source.id}: {exc}"
                errors.append(message)
                logger.exception("Source %s failed", source.id)
                continue
            sources_ok += 1
            logger.info("%s returned %s item(s)", source.id, len(items))
            for item in items:
                fetched += 1
                opportunity = prepare_opportunity(item, now)
                if is_distinctive_title(opportunity.title_key):
                    canonical = self.repository.find_canonical_url(opportunity.title_key, opportunity.url)
                    if canonical:
                        opportunity = opportunity.model_copy(update={"duplicate_of": canonical})
                existing = self.repository.get_by_url(opportunity.url)
                if existing and existing.content_hash == opportunity.content_hash and _same_classification(existing, opportunity):
                    continue
                if self._should_enrich(opportunity, budget):
                    try:
                        opportunity = self.enricher.enrich(opportunity)
                    except EnrichmentError as exc:
                        logger.warning("Enrichment skipped for %s: %s", opportunity.url, exc)
                    budget -= 1
                _, did_change = self.repository.upsert_opportunity(opportunity)
                if did_change:
                    changed += 1
        return fetched, changed, sources_ok, errors

    def _should_enrich(self, opportunity, budget: int) -> bool:
        return bool(
            getattr(self.enricher, "enabled", False)
            and budget > 0
            and not opportunity.duplicate_of
            and opportunity.confidence < self.settings.llm.confidence_below
        )

    def _score(self, now: datetime) -> None:
        today = now.date()
        for opportunity in self.repository.list_opportunities():
            for profile in self.profiles:
                decision = score_opportunity(profile, opportunity, today)
                self.repository.upsert_match(
                    opportunity.id,
                    profile.id,
                    decision.score,
                    decision.reasons,
                    decision.accepted,
                    decision.reject_reason,
                    now,
                )

    def _deliver(self, profile: UserProfile, now: datetime) -> int:
        pending = self.repository.pending_for(profile.id)
        channels = [channel for channel in self.distributors if channel.handles(profile)]
        if not pending or not channels:
            return 0
        for channel in channels:
            remaining = [
                item
                for item in pending
                if channel.name not in self.repository.successful_channels(item.match_id)
            ]
            if not remaining:
                continue
            digest = _digest(profile, remaining, channel.name, now)
            try:
                channel.deliver(profile, digest)
            except DeliveryError as exc:
                logger.error("%s failed for %s: %s", channel.name, profile.id, exc)
                for item in remaining:
                    self.repository.record_delivery(item.match_id, channel.name, "failed", str(exc), now)
                continue
            for item in remaining:
                self.repository.record_delivery(item.match_id, channel.name, "sent", "", now)
        required = {channel.name for channel in channels}
        sent = 0
        for item in pending:
            if required <= self.repository.successful_channels(item.match_id):
                self.repository.mark_sent(item.match_id, now)
                sent += 1
        return sent

    def _previews(self) -> list[str]:
        lines: list[str] = []
        for profile in self.profiles:
            pending = self.repository.pending_for(profile.id)
            if not pending:
                lines.append(f"{profile.display_name}: nothing new")
                continue
            titles = "; ".join(item.opportunity.title for item in pending)
            lines.append(f"{profile.display_name}: {len(pending)} ({titles})")
        return lines

    def _now(self) -> datetime:
        return self.clock()

    def _report(self, started, finished, dry_run, sources_ok, errors, fetched, changed, previews, delivered):
        return RunReport(
            started_at=started,
            finished_at=finished,
            dry_run=dry_run,
            sources_ok=sources_ok,
            source_errors=errors,
            fetched=fetched,
            changed=changed,
            previews=previews,
            delivered=delivered,
        )


def _digest(profile: UserProfile, pending: list[PendingMatch], channel: str, now: datetime) -> Digest:
    items = [
        DigestItem(
            match_id=item.match_id,
            title=item.opportunity.title,
            url=item.opportunity.url,
            source_id=item.opportunity.source_id,
            organization=item.opportunity.organization,
            summary=item.opportunity.ai_summary or _clip(item.opportunity.summary, 320),
            score=item.score,
            reasons=item.reasons,
            countries=item.opportunity.countries,
            funding=item.opportunity.funding,
            deadline=item.opportunity.deadline,
            published_at=item.opportunity.published_at,
        )
        for item in pending
    ]
    return Digest(
        profile_id=profile.id,
        display_name=profile.display_name,
        generated_at=now,
        items=items,
        channel=channel,
    )


def _same_classification(existing, opportunity) -> bool:
    return (
        list(existing.degree_levels) == list(opportunity.degree_levels)
        and list(existing.opportunity_types) == list(opportunity.opportunity_types)
        and existing.is_actionable == opportunity.is_actionable
        and list(existing.countries) == list(opportunity.countries)
        and existing.funding == opportunity.funding
        and existing.deadline == opportunity.deadline
    )


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
