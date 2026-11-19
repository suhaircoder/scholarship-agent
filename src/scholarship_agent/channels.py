"""Delivery channels. A failed channel does not cancel the others."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from scholarship_agent.errors import DeliveryError
from scholarship_agent.models import Digest
from scholarship_agent.profiles import EmailSettings, UserProfile
from scholarship_agent.render import render_html, render_markdown, render_plain, render_telegram_messages

logger = logging.getLogger(__name__)


class FileDistributor:
    name = "file"

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def handles(self, profile: UserProfile) -> bool:
        return True

    def deliver(self, profile: UserProfile, digest: Digest) -> None:
        folder = self.directory / digest.generated_at.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = digest.generated_at.strftime("%Y%m%dT%H%M%SZ")
        markdown_path = folder / f"{profile.id}-{stamp}.md"
        html_path = folder / f"{profile.id}-{stamp}.html"
        markdown_path.write_text(render_markdown(digest), encoding="utf-8")
        html_path.write_text(render_html(digest), encoding="utf-8")
        logger.info("Wrote digest %s", markdown_path)


class LogDistributor:
    name = "log"

    def handles(self, profile: UserProfile) -> bool:
        return True

    def deliver(self, profile: UserProfile, digest: Digest) -> None:
        logger.info("Digest for %s\n%s", profile.display_name, render_plain(digest))


class EmailDistributor:
    name = "email"

    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    def handles(self, profile: UserProfile) -> bool:
        return bool(profile.resolved_email)

    def deliver(self, profile: UserProfile, digest: Digest) -> None:
        message = build_email(
            sender=_required(self._settings.from_env),
            recipient=profile.resolved_email,
            digest=digest,
        )
        host = _required(self._settings.host_env)
        port = int(_env(self._settings.port_env, "587"))
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if self._settings.use_tls:
                    smtp.starttls()
                username = _env(self._settings.username_env, "")
                password = _env(self._settings.password_env, "")
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryError(f"Email to {profile.resolved_email} failed") from exc
        logger.info("Emailed %s match(es) to %s", len(digest.items), profile.id)


class TelegramDistributor:
    name = "telegram"

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    def handles(self, profile: UserProfile) -> bool:
        return bool(profile.resolved_telegram_chat_id)

    def deliver(self, profile: UserProfile, digest: Digest) -> None:
        endpoint = f"https://api.telegram.org/bot{self._token}/sendMessage"
        for text in render_telegram_messages(digest):
            try:
                response = self._client.post(
                    endpoint,
                    json={
                        "chat_id": profile.resolved_telegram_chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    },
                )
            except httpx.HTTPError as exc:
                raise DeliveryError("Telegram delivery failed") from exc
            if response.status_code >= 400:
                raise DeliveryError(f"Telegram delivery failed with status {response.status_code}")
        logger.info("Sent Telegram digest to %s", profile.id)


def build_email(*, sender: str, recipient: str, digest: Digest) -> EmailMessage:
    message = EmailMessage()
    count = len(digest.items)
    message["Subject"] = f"{count} academic match{'' if count == 1 else 'es'} for {digest.display_name}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(render_plain(digest))
    message.add_alternative(render_html(digest), subtype="html")
    return message


def _env(name: str, default: str) -> str:
    import os

    return os.getenv(name, default).strip()


def _required(name: str) -> str:
    value = _env(name, "")
    if not value:
        raise DeliveryError(f"{name} is not set")
    return value
