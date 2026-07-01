from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config
from .service import BotService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medium-bot",
        description="Generate daily technical drafts and publish only after human approval.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="bot project directory")
    parser.add_argument("--env-file", type=Path, help="environment file (default: ROOT/.env)")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="generate today's draft")
    generate.add_argument("--date", type=date.fromisoformat)
    generate.add_argument("--topic", help="override the rotating topic area")
    generate.add_argument("--force", action="store_true", help="replace this date's draft")

    commands.add_parser("list", help="list tracked drafts and published posts")
    commands.add_parser("topics", help="show the editable topic queue and usage status")
    commands.add_parser("scheduled", help="generate only during the configured local hour")

    publish = commands.add_parser("publish", help="review and explicitly approve one Medium post")
    publish.add_argument("draft", type=Path)
    publish.add_argument("--status", choices=("public", "draft", "unlisted"), default="public")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        config = Config.from_env(root, args.env_file)
        service = BotService(config)
        if args.command == "generate":
            day = args.date or datetime.now(ZoneInfo(config.timezone)).date()
            path = service.generate(day, args.topic, args.force)
            print(path)
            return 0
        if args.command == "scheduled":
            now = datetime.now(ZoneInfo(config.timezone))
            existing = service.history.for_date(now.date().isoformat())
            if existing:
                existing_path = Path(str(existing.get("path", "")))
                if existing_path.exists():
                    print(existing_path)
                    return 0
            if now.hour < config.daily_hour:
                print(
                    f"Waiting for generation hour in {config.timezone}: "
                    f"current={now.hour:02d}, configured={config.daily_hour:02d}"
                )
                return 0
            path = service.generate(now.date())
            print(path)
            return 0
        if args.command == "list":
            entries = service.history.load()
            if not entries:
                print("No drafts yet.")
            for item in entries:
                suffix = f" -> {item['url']}" if item.get("url") else ""
                print(f"{item['date']}  {item['status']:<9}  {item['title']}{suffix}")
            return 0
        if args.command == "topics":
            for topic, used in service.topics.statuses(service.history.load()):
                print(f"{'used' if used else 'pending':<7}  {topic}")
            return 0
        if args.command == "publish":
            draft_path = args.draft.resolve()
            if not sys.stdin.isatty():
                raise RuntimeError("publishing requires an interactive terminal and human approval")
            from .models import read_draft

            draft = read_draft(draft_path)
            print(f"\nReady to publish: {draft.title}\nFile: {draft_path}\nStatus: {args.status}\n")
            expected = f"PUBLISH {draft.title}"
            approval = input(f"Type exactly {expected!r} to continue: ")
            if approval != expected:
                print("Cancelled.")
                return 2
            result = service.publish(draft_path, args.status)
            print(result.url or f"Published Medium post {result.post_id}")
            return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
