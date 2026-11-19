"""Plain, Markdown, and HTML digests."""

from __future__ import annotations

import html

from scholarship_agent.models import Digest, DigestItem


def render_plain(digest: Digest) -> str:
    lines = [
        f"{digest.display_name}: {len(digest.items)} new academic match"
        f"{'' if len(digest.items) == 1 else 'es'}",
        "",
    ]
    for item in digest.items:
        lines.extend(_plain_item(item))
    return "\n".join(lines).strip() + "\n"


def render_markdown(digest: Digest) -> str:
    lines = [
        f"# {digest.display_name}",
        "",
        f"{len(digest.items)} new match{'' if len(digest.items) == 1 else 'es'} · "
        f"{digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    for item in digest.items:
        lines.append(f"## [{item.title}]({item.url})")
        lines.append("")
        lines.append(_meta(item))
        if item.summary:
            lines.extend(["", item.summary])
        if item.reasons:
            lines.extend(["", "*" + "; ".join(item.reasons) + "*"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_html(digest: Digest) -> str:
    cards = "\n".join(_html_item(item) for item in digest.items)
    title = html.escape(digest.display_name)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title} academic matches</title>
</head>
<body style="font-family: Georgia, serif; color: #1c1917; max-width: 720px; margin: 2rem auto; padding: 0 1rem;">
  <h1 style="font-weight: normal;">{title}</h1>
  <p>{len(digest.items)} new match{"" if len(digest.items) == 1 else "es"}</p>
  {cards}
</body>
</html>
"""


def render_telegram_messages(digest: Digest, limit: int = 3900) -> list[str]:
    header = f"<b>{html.escape(digest.display_name)}</b>\n{len(digest.items)} new academic matches\n"
    messages: list[str] = []
    current = header
    for item in digest.items:
        block = "\n" + _telegram_item(item)
        if len(current) + len(block) > limit and current != header:
            messages.append(current.strip())
            current = header + block
        else:
            current += block
    if current.strip():
        messages.append(current.strip())
    return messages


def _plain_item(item: DigestItem) -> list[str]:
    lines = [item.title, item.url, _meta(item)]
    if item.summary:
        lines.append(item.summary)
    if item.reasons:
        lines.append("; ".join(item.reasons))
    lines.append("")
    return lines


def _meta(item: DigestItem) -> str:
    parts = [item.source_id.replace("_", " "), f"score {item.score:.0f}"]
    if item.organization:
        parts.insert(0, item.organization)
    if item.countries:
        parts.append(", ".join(item.countries))
    if item.funding == "fully_funded":
        parts.append("fully funded")
    elif item.funding == "partial":
        parts.append("partial funding")
    if item.deadline:
        parts.append(f"deadline {item.deadline.isoformat()}")
    return " · ".join(parts)


def _html_item(item: DigestItem) -> str:
    summary = f"<p>{html.escape(item.summary)}</p>" if item.summary else ""
    reasons = ""
    if item.reasons:
        reasons = "<p style='color:#57534e'>" + html.escape("; ".join(item.reasons)) + "</p>"
    return f"""<article style="border-top: 1px solid #d6d3d1; padding: 1rem 0;">
  <h2 style="font-size: 1.15rem; font-weight: normal;"><a href="{html.escape(item.url, quote=True)}">{html.escape(item.title)}</a></h2>
  <p>{html.escape(_meta(item))}</p>
  {summary}
  {reasons}
</article>"""


def _telegram_item(item: DigestItem) -> str:
    title = html.escape(item.title)
    url = html.escape(item.url, quote=True)
    lines = [f'<a href="{url}">{title}</a>', html.escape(_meta(item))]
    if item.summary:
        lines.append(html.escape(item.summary[:500]))
    return "\n".join(lines)
