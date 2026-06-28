# Medium DevOps Bot

Generates one original DevOps, infrastructure, or MLOps draft per day. Topics come from an
editable queue, previous titles are supplied to the model to reduce repetition, and generated
posts are stored as editable Markdown in `outbox/`.

## Manage topics

Edit [`topics.txt`](topics.txt) and put one desired article topic on each line. The daily job uses
the first topic that has not appeared in `data/history.json`. Blank lines and `#` comments are
ignored. Duplicate and strongly overlapping topics are detected case-insensitively with
punctuation and word order normalized. A topic already used on another date is rejected.

```bash
PYTHONPATH=src python3 -m medium_bot.cli --root "$PWD" topics
```

The output labels each topic as `pending` or `used`. Add new topics whenever the pending queue is
low. When every topic is used, the daily job exits with an explanation instead of repeating one.

Publishing deliberately requires a human at an interactive terminal. Medium no longer issues
new API integration tokens, and its API terms disallow unattended posting of automatically
generated content. If you do not already have a token, review the Markdown and paste it into
Medium's editor manually.

## Setup

```bash
cd /home/madhuchilipi/dev/medium-devops-bot
cp .env.example .env
```

Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey) and
add it as `GEMINI_API_KEY` in `.env`. The default `gemini-2.5-flash-lite` model has free-tier
input and output tokens. Free-tier content may be used by Google to improve its products, so do
not put private company data in article prompts.

To use OpenAI instead, set `LLM_PROVIDER=openai` and add `OPENAI_API_KEY`.

If your Medium account already has a working integration token,
also add `MEDIUM_ACCESS_TOKEN`. The bot is configured for
`https://medium.com/devops-diaries-hub`; with an existing token it resolves the publication's
internal ID from the slug. `MEDIUM_PUBLICATION_ID` remains available as an explicit override.

## Use it

Generate today's draft:

```bash
PYTHONPATH=src python3 -m medium_bot.cli --root "$PWD" generate
```

Generate a requested topic or replace today's draft:

```bash
PYTHONPATH=src python3 -m medium_bot.cli --root "$PWD" generate --topic "Kubernetes admission control" --force
```

Review/edit the generated Markdown, then publish from an interactive shell:

```bash
PYTHONPATH=src python3 -m medium_bot.cli --root "$PWD" publish outbox/2026-06-27-example.md
```

The command shows the title and requires you to type a title-specific confirmation. It cannot
publish from cron or another non-interactive process. Use `--status draft` or `--status unlisted`
when appropriate.

## Schedule daily generation

Make the runner executable and add it to your crontab. This example runs at 8:00 AM local time:

```bash
chmod +x scripts/run-daily.sh
crontab -e
```

```cron
0 8 * * * /home/madhuchilipi/dev/medium-devops-bot/scripts/run-daily.sh >> /home/madhuchilipi/dev/medium-devops-bot/data/cron.log 2>&1
```

The scheduled command checks `BOT_TIMEZONE` and `BOT_DAILY_HOUR`, so it remains correct when the
host uses another timezone. The generator is idempotent: a second run on the same date returns
the existing draft. `--force` is intentionally required to replace it.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Secrets are read from environment variables or `.env`; `.env`, generated drafts, and history are
excluded from git.

The bot uses only Python's standard library; no package installation is required. An optional
`pip install -e .` exposes the shorter `medium-bot` command on hosts where pip is available.
