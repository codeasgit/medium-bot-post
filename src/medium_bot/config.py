from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path) -> None:
    """Load a small, shell-free .env file without overriding real env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    root: Path
    openai_api_key: str
    openai_model: str
    medium_access_token: str
    medium_publication_id: str
    author_name: str
    timezone: str
    min_words: int
    max_words: int
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    medium_publication_slug: str = ""
    medium_publication_url: str = ""
    medium_publication_name: str = ""
    daily_hour: int = 8

    @classmethod
    def from_env(cls, root: Path, env_file: Path | None = None) -> "Config":
        load_env_file(env_file or root / ".env")
        min_words = int(os.getenv("BOT_MIN_WORDS", "800"))
        max_words = int(os.getenv("BOT_MAX_WORDS", "1600"))
        if min_words < 300 or max_words <= min_words:
            raise ValueError("BOT_MIN_WORDS must be >= 300 and lower than BOT_MAX_WORDS")
        provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
        if provider not in {"gemini", "openai"}:
            raise ValueError("LLM_PROVIDER must be gemini or openai")
        daily_hour = int(os.getenv("BOT_DAILY_HOUR", "8"))
        if not 0 <= daily_hour <= 23:
            raise ValueError("BOT_DAILY_HOUR must be between 0 and 23")
        return cls(
            root=root,
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            medium_access_token=os.getenv("MEDIUM_ACCESS_TOKEN", ""),
            medium_publication_id=os.getenv("MEDIUM_PUBLICATION_ID", ""),
            author_name=os.getenv("BOT_AUTHOR_NAME", "DevOps Practitioner"),
            timezone=os.getenv("BOT_TIMEZONE", "America/Chicago"),
            min_words=min_words,
            max_words=max_words,
            llm_provider=provider,
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            medium_publication_slug=os.getenv("MEDIUM_PUBLICATION_SLUG", ""),
            medium_publication_url=os.getenv("MEDIUM_PUBLICATION_URL", ""),
            medium_publication_name=os.getenv("MEDIUM_PUBLICATION_NAME", ""),
            daily_hour=daily_hour,
        )

    @property
    def outbox(self) -> Path:
        return self.root / "outbox"

    @property
    def history_file(self) -> Path:
        return self.root / "data" / "history.json"

    @property
    def topics_file(self) -> Path:
        configured = os.getenv("BOT_TOPICS_FILE", "topics.txt")
        path = Path(configured)
        return path if path.is_absolute() else self.root / path
