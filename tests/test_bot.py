from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from medium_bot.config import Config
from medium_bot.generator import ArticleGenerator
from medium_bot.medium import PublishResult
from medium_bot.models import GeneratedArticle, read_draft, word_count
from medium_bot.service import BotService


BODY = "\n\n".join(
    [
        "## Context\n" + "Reliable systems need explicit ownership and feedback loops. " * 90,
        "## Implementation\n" + "Start with a small change, measure it, and document the result. " * 90,
        "## Tradeoffs\n" + "Every control adds cost, so match the control to the operational risk. " * 90,
    ]
)


class FakeGenerator:
    def generate(self, topic: str, previous_titles: list[str]) -> GeneratedArticle:
        return GeneratedArticle(
            title="A Practical Reliability Loop for Platform Teams",
            subtitle="Turn operational signals into small, measurable improvements without adding ceremony.",
            tags=["DevOps", "SRE", "Platform Engineering"],
            body_markdown=BODY,
        )


class FakeMedium:
    def publish(self, draft, status: str) -> PublishResult:
        return PublishResult("https://medium.example/post", "abc", status)


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class ResolvingMedium:
    def __init__(self, config: Config):
        from medium_bot.medium import MediumClient

        self.client = MediumClient(config)
        self.requests: list[tuple[str, str]] = []

        def request(method, path, payload=None):
            self.requests.append((method, path))
            if path == "/me":
                return {"data": {"id": "author-1"}}
            if path == "/users/author-1/publications":
                return {
                    "data": [
                        {
                            "id": "publication-1",
                            "name": "DevOps-Diaries-Hub",
                            "url": "https://medium.com/devops-diaries-hub",
                        }
                    ]
                }
            if path == "/publications/publication-1/posts":
                return {
                    "data": {
                        "id": "post-1",
                        "url": "https://medium.com/devops-diaries-hub/post-1",
                        "publishStatus": "draft",
                    }
                }
            raise AssertionError(path)

        self.client._request = request


class BotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = Config(
            root=root,
            openai_api_key="test",
            openai_model="test-model",
            medium_access_token="existing-token",
            medium_publication_id="",
            author_name="Test Author",
            timezone="America/Chicago",
            min_words=300,
            max_words=3000,
        )
        self.service = BotService(self.config)
        self.config.topics_file.write_text(
            "First unique platform topic\nSecond unique MLOps topic\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_generate_is_idempotent_for_a_date(self) -> None:
        day = date(2026, 6, 27)
        first = self.service.generate(day, generator=FakeGenerator())
        second = self.service.generate(day, generator=FakeGenerator())
        self.assertEqual(first, second)
        self.assertEqual(len(self.service.history.load()), 1)
        draft = read_draft(first)
        self.assertEqual(draft.title, "A Practical Reliability Loop for Platform Teams")
        self.assertGreater(word_count(draft.content), 300)

    def test_publish_updates_history(self) -> None:
        path = self.service.generate(date(2026, 6, 27), generator=FakeGenerator())
        result = self.service.publish(path, "public", client=FakeMedium())
        self.assertEqual(result.url, "https://medium.example/post")
        entry = self.service.history.load()[0]
        self.assertEqual(entry["status"], "public")
        self.assertEqual(entry["url"], result.url)

    def test_topic_rotation_covers_all_three_areas(self) -> None:
        topics = {self.service.topic_for(date(2026, 6, day)) for day in (25, 26, 27)}
        self.assertEqual(len(topics), 3)

    def test_topic_queue_advances_and_skips_used_topics(self) -> None:
        first = self.service.generate(date(2026, 6, 27), generator=FakeGenerator())
        self.assertEqual(read_draft(first).metadata["topic"], "First unique platform topic")
        second = self.service.generate(date(2026, 6, 28), generator=FakeGenerator())
        self.assertEqual(read_draft(second).metadata["topic"], "Second unique MLOps topic")

    def test_duplicate_topics_in_file_are_rejected(self) -> None:
        self.config.topics_file.write_text(
            "Kubernetes capacity planning\nkubernetes capacity-planning\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate topic"):
            self.service.topics.load()

    def test_reordered_topics_are_treated_as_duplicates(self) -> None:
        self.config.topics_file.write_text(
            "Kubernetes capacity planning guide\nA guide for capacity planning Kubernetes\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate topic"):
            self.service.topics.load()

    def test_explicitly_reused_topic_is_rejected(self) -> None:
        topic = "A custom Terraform migration plan"
        self.service.generate(date(2026, 6, 27), topic=topic, generator=FakeGenerator())
        with self.assertRaisesRegex(ValueError, "already used"):
            self.service.generate(date(2026, 6, 28), topic=topic, generator=FakeGenerator())

    def test_extracts_structured_response_text(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"title":"example"}'}],
                }
            ]
        }
        self.assertEqual(ArticleGenerator._output_text(payload), '{"title":"example"}')

    def test_extracts_gemini_response_text(self) -> None:
        payload = {
            "candidates": [
                {"content": {"parts": [{"text": '{"title":"gemini example"}'}]}}
            ]
        }
        self.assertEqual(
            ArticleGenerator._gemini_output_text(payload), '{"title":"gemini example"}'
        )

    def test_transient_api_failure_is_retried(self) -> None:
        unavailable = HTTPError(
            "https://example.test",
            503,
            "Unavailable",
            {},
            BytesIO(b'{"error":"busy"}'),
        )
        response = FakeResponse(b'{"ok":true}')
        with patch("medium_bot.generator.urlopen", side_effect=[unavailable, response]) as call:
            with patch("medium_bot.generator.time.sleep"):
                result = ArticleGenerator._json_request(
                    "https://example.test", {"Content-Type": "application/json"}, {}, "Test"
                )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(call.call_count, 2)

    def test_resolves_publication_slug_to_medium_id(self) -> None:
        config = Config(
            **{
                **self.config.__dict__,
                "medium_publication_slug": "devops-diaries-hub",
                "medium_publication_url": "https://medium.com/devops-diaries-hub",
                "medium_publication_name": "DevOps-Diaries-Hub",
            }
        )
        resolving = ResolvingMedium(config)
        path = self.service.generate(date(2026, 6, 27), generator=FakeGenerator())
        result = resolving.client.publish(read_draft(path), "draft")
        self.assertEqual(result.post_id, "post-1")
        self.assertIn(("POST", "/publications/publication-1/posts"), resolving.requests)


if __name__ == "__main__":
    unittest.main()
