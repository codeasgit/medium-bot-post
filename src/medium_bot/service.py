from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config
from .generator import ArticleGenerator
from .history import History
from .medium import MediumClient, PublishResult
from .models import read_draft, render_draft, slugify
from .topics import TopicQueue


TOPIC_ROTATION = (
    "DevOps delivery practices, CI/CD reliability, or developer experience",
    "cloud infrastructure, Kubernetes operations, Terraform, networking, or observability",
    "MLOps systems, model delivery, feature/data pipelines, evaluation, or monitoring",
)


class BotService:
    def __init__(self, config: Config):
        self.config = config
        self.history = History(config.history_file)
        self.topics = TopicQueue(config.topics_file)

    @staticmethod
    def topic_for(day: date) -> str:
        return TOPIC_ROTATION[day.toordinal() % len(TOPIC_ROTATION)]

    def generate(
        self,
        day: date,
        topic: str | None = None,
        force: bool = False,
        generator: ArticleGenerator | None = None,
    ) -> Path:
        date_string = day.isoformat()
        existing = self.history.for_date(date_string)
        if existing and not force:
            path = Path(str(existing["path"]))
            if path.exists():
                return path

        entries = self.history.load()
        if topic:
            self.topics.ensure_unused(
                topic,
                entries,
                replacing_date=date_string if force else None,
            )
            selected_topic = topic.strip()
        else:
            selected_topic = self.topics.next_unused(entries)
        previous_titles = [str(item["title"]) for item in entries if item.get("title")]
        article = (generator or ArticleGenerator(self.config)).generate(selected_topic, previous_titles)
        now = datetime.now(ZoneInfo(self.config.timezone))
        self.config.outbox.mkdir(parents=True, exist_ok=True)
        path = self.config.outbox / f"{date_string}-{slugify(article.title)}.md"
        path.write_text(
            render_draft(
                article,
                selected_topic,
                now,
                self.config.medium_publication_name,
                self.config.medium_publication_url,
            ),
            encoding="utf-8",
        )

        if existing and force:
            old_path = Path(str(existing.get("path", "")))
            if old_path != path and old_path.exists() and old_path.parent == self.config.outbox:
                old_path.unlink()
        self.history.record(
            {
                "date": date_string,
                "title": article.title,
                "topic": selected_topic,
                "path": str(path.resolve()),
                "status": "draft",
            }
        )
        return path

    def publish(self, path: Path, status: str, client: MediumClient | None = None) -> PublishResult:
        draft = read_draft(path)
        result = (client or MediumClient(self.config)).publish(draft, status)
        self.history.mark_published(path, result.url, result.status)
        return result
