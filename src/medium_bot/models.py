from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class GeneratedArticle:
    title: str
    subtitle: str
    tags: list[str]
    body_markdown: str

    def __post_init__(self) -> None:
        if not 12 <= len(self.title) <= 100:
            raise ValueError("title must be 12-100 characters")
        if not 20 <= len(self.subtitle) <= 180:
            raise ValueError("subtitle must be 20-180 characters")
        if not 2 <= len(self.tags) <= 3:
            raise ValueError("article must have 2-3 tags")
        cleaned = [tag.strip() for tag in self.tags]
        if any(not tag or len(tag) > 25 for tag in cleaned):
            raise ValueError("tags must be 1-25 characters")
        if len({tag.casefold() for tag in cleaned}) != len(cleaned):
            raise ValueError("tags must be unique")
        object.__setattr__(self, "tags", cleaned)
        body = self.body_markdown.strip()
        if len(body) < 1000:
            raise ValueError("article body is too short")
        if len(re.findall(r"^##\s+", body, flags=re.MULTILINE)) < 3:
            raise ValueError("article needs at least three H2 sections")
        object.__setattr__(self, "body_markdown", body)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GeneratedArticle":
        try:
            return cls(
                title=str(value["title"]),
                subtitle=str(value["subtitle"]),
                tags=[str(tag) for tag in value["tags"]],  # type: ignore[union-attr]
                body_markdown=str(value["body_markdown"]),
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid generated article: {error}") from error


class Draft:
    def __init__(self, path: Path, metadata: dict[str, object], content: str):
        self.path = path
        self.metadata = metadata
        self.content = content.strip()

    @property
    def title(self) -> str:
        return str(self.metadata["title"])

    @property
    def tags(self) -> list[str]:
        return [str(tag) for tag in self.metadata.get("tags", [])]


def slugify(value: str, limit: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:limit].rstrip("-") or "article"


def word_count(markdown: str) -> int:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"[#>*_`\[\]()-]", " ", text)
    return len(re.findall(r"\b[\w][\w'-]*\b", text))


def render_draft(
    article: GeneratedArticle,
    topic: str,
    generated_at: datetime,
    publication_name: str = "",
    publication_url: str = "",
) -> str:
    import json

    metadata = {
        "title": article.title,
        "subtitle": article.subtitle,
        "tags": article.tags,
        "topic": topic,
        "generated_at": generated_at.isoformat(),
        "status": "draft",
    }
    if publication_name:
        metadata["publication"] = publication_name
    if publication_url:
        metadata["publication_url"] = publication_url
    frontmatter = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
    )
    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {article.title}\n\n> {article.subtitle}\n\n{article.body_markdown.strip()}\n"
    )


def read_draft(path: Path) -> Draft:
    import json

    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError(f"{path} does not contain valid bot frontmatter")
    frontmatter, content = raw[4:].split("\n---\n", 1)
    metadata: dict[str, object] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = json.loads(value.strip())
    if not metadata.get("title"):
        raise ValueError(f"{path} is missing a title")
    return Draft(path, metadata, content)
