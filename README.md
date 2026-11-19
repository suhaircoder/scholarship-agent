# Scholarship Agent

The agent reads public academic feeds, keeps the listings that fit each person, and writes a separate digest. Two profiles are included:

- **PhD** receives PhD scholarships and PhD positions worldwide.
- **Master** receives master's scholarships and master's positions worldwide.

A faculty job, a postdoc post, or a "7 universities" article does not go to either of you. The first runs only saw five PhD matches because the EURAXESS RSS feed is a short recent window and most of those jobs are faculty posts. Category feeds and eight pages of the public EURAXESS search widen that window. A department then keeps the listings that name that field.

Feeds only contain recent posts. The first run is not a historical archive. Leave it scheduled and it will keep up with new posts.

## What it does on each run

1. Reads the enabled RSS feeds in `config/sources.yaml`, using conditional requests so an unchanged feed is skipped.
2. Classifies each new post: degree, listing type, country, funding, and deadline.
3. Scores it against every profile. A sent listing is not sent again.
4. Writes a Markdown and HTML digest per person to `data/digests/`. Email and Telegram are optional.
5. If a channel fails, that channel is retried on the next run. A channel that already succeeded is not repeated.

The classifier is deterministic, so the same post always gets the same decision. An OpenAI-compatible model can re-read posts the rules are unsure about. It is off until you set a key.

## Setup

From this folder:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Check that the feeds respond:

```powershell
scholarship-agent check
```

Run once:

```powershell
scholarship-agent run
```

Open the finder in the browser:

```powershell
python app.py
```

The page is at http://127.0.0.1:8765/. **PhD** and **Master** are the two worldwide searches. Type a country and a department on Scholarships, then save a result into **Portfolio**. Stop the site with Ctrl+C.

Preview without saving or sending:

```powershell
scholarship-agent run --dry-run
```

Show the two profiles:

```powershell
scholarship-agent profiles
```

## Narrow the search

Both searches are worldwide until you type a department or pick a country. To add another saved tab, copy `config/users/me.yaml` and change `id` and `display_name`.

A friend who only needs one search can open Scholarships, type a department, and pick a country. Saved scholarships go to Portfolio.

```yaml
countries:
  - Germany
  - Netherlands
department: computer-science
disciplines: []
```

An empty `countries` list means worldwide. `keywords_exclude` is compared with the title only, so a PhD opening supervised by an assistant professor still comes through.

To keep only awards that state full funding:

```yaml
funding_preference:
  - fully_funded
allow_unknown_funding: false
```

Many official posts describe the salary in a document the feed does not include, so the default allows unknown funding.

## Schedule it

The EURAXESS feed is a short recent window, so the default interval is 2 hours.

Leave a window open:

```powershell
scholarship-agent run --loop
```

Or register a task that runs one pass and exits:

```powershell
schtasks /Create /TN "ScholarshipAgent" /SC HOURLY /MO 2 /TR "cmd /c cd /d \"d:\my cv\sholarship-agent\" && .venv\Scripts\scholarship-agent.exe run"
```

## Email and Telegram

In `.env`:

```
ME_EMAIL=you@example.com
SISTER_EMAIL=sister@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=the-mailbox-password
SMTP_FROM=you@example.com
```

In `config/settings.yaml` set `delivery.email.enabled` to `true`.

For Telegram, set `delivery.telegram.enabled` to `true`, put the bot token in `TELEGRAM_BOT_TOKEN`, and put each chat id in `ME_TELEGRAM_CHAT_ID` and `SISTER_TELEGRAM_CHAT_ID`.

## Optional model

Set `llm.enabled` to `true` and `OPENAI_API_KEY` in `.env`. Any server that implements `POST /chat/completions` works. Set `OPENAI_BASE_URL` for a local server. Posts the rules already classify with high confidence are not sent to the model.

## Add a source

Add an `rss` entry to `config/sources.yaml`. Use a feed the site already publishes for readers. If a site answers 403 or 404, disable that source. The agent does not bypass blocks, solve challenges, or crawl HTML search pages.

## Tests

```powershell
pytest
```

## Layout

- `config/users/` — one file per person
- `config/sources.yaml` — feeds
- `src/scholarship_agent/classify.py` — degree and listing rules
- `src/scholarship_agent/score.py` — profile matching
- `src/scholarship_agent/agent.py` — the run
- `data/` — database, digests, and logs; not committed
