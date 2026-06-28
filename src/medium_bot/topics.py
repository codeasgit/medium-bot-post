from __future__ import annotations

import re
from pathlib import Path


def normalize_topic(topic: str) -> str:
    """Normalize topics for duplicate comparison without changing display text."""
    return " ".join(re.findall(r"[a-z0-9]+", topic.casefold()))


def topics_are_similar(left: str, right: str) -> bool:
    left_normalized = normalize_topic(left)
    right_normalized = normalize_topic(right)
    if left_normalized == right_normalized:
        return True
    stop_words = {"a", "an", "the", "for", "to", "of", "and", "in", "on", "with", "how"}
    left_tokens = set(left_normalized.split()) - stop_words
    right_tokens = set(right_normalized.split()) - stop_words
    if not left_tokens or not right_tokens:
        return False
    similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return similarity >= 0.8


class TopicQueue:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[str]:
        if not self.path.exists():
            raise ValueError(
                f"topic file not found: {self.path}. Add one topic per line before generating."
            )
        topics: list[str] = []
        seen: list[tuple[str, int]] = []
        for line_number, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            topic = raw.strip()
            if not topic or topic.startswith("#"):
                continue
            normalized = normalize_topic(topic)
            if not normalized:
                continue
            for earlier_topic, earlier_line in seen:
                if topics_are_similar(topic, earlier_topic):
                    raise ValueError(
                        f"duplicate topic in {self.path}: lines {earlier_line} and {line_number}"
                    )
            seen.append((topic, line_number))
            topics.append(topic)
        if not topics:
            raise ValueError(f"no topics found in {self.path}")
        return topics

    def statuses(self, history: list[dict[str, object]]) -> list[tuple[str, bool]]:
        used = [
            str(item["topic"])
            for item in history
            if item.get("topic")
        ]
        return [
            (topic, any(topics_are_similar(topic, previous) for previous in used))
            for topic in self.load()
        ]

    def next_unused(self, history: list[dict[str, object]]) -> str:
        for topic, used in self.statuses(history):
            if not used:
                return topic
        raise ValueError(
            f"all topics in {self.path} have been used; add a new unique topic for the next draft"
        )

    @staticmethod
    def ensure_unused(
        topic: str,
        history: list[dict[str, object]],
        replacing_date: str | None = None,
    ) -> None:
        normalized = normalize_topic(topic)
        if not normalized:
            raise ValueError("topic cannot be empty")
        for item in history:
            if replacing_date and item.get("date") == replacing_date:
                continue
            if item.get("topic") and topics_are_similar(topic, str(item["topic"])):
                raise ValueError(
                    f"topic was already used on {item.get('date')}: {item.get('topic')}"
                )
