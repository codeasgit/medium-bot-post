from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config
from .models import GeneratedArticle, word_count


SYSTEM_PROMPT = """You are a senior platform engineer and careful technical editor.
Write original, practical Medium articles for working engineers. Prefer durable engineering
principles and runnable examples over hype. Never invent benchmarks, incidents, quotes,
product behavior, or sources. When a detail may vary by version, explicitly tell the reader
to check the relevant official documentation. Do not claim personal experience you do not
have. Return clean Markdown, but do not repeat the title or subtitle inside body_markdown.
Include at least three ## sections, one concrete example or checklist, tradeoffs, and a short
conclusion. Before returning, check every code sample for internal consistency, avoid passing
secrets in command-line arguments, and avoid unnecessarily stale runtime versions. Avoid
generic AI phrases and sales language."""


class ArticleGenerator:
    def __init__(self, config: Config):
        if config.llm_provider == "gemini" and not config.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required. Create a free key at "
                "https://aistudio.google.com/app/apikey"
            )
        if config.llm_provider == "openai" and not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self.config = config

    @staticmethod
    def _article_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "A specific title under 100 characters."},
                "subtitle": {"type": "string", "description": "A useful subtitle under 180 characters."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 3,
                },
                "body_markdown": {
                    "type": "string",
                    "description": "The complete article body as Markdown, without title or subtitle.",
                },
            },
            "required": ["title", "subtitle", "tags", "body_markdown"],
            "additionalProperties": False,
        }

    @staticmethod
    def _json_request(url: str, headers: dict[str, str], payload: dict[str, Any], provider: str) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        transient_codes = {429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                with urlopen(request, timeout=180) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                if error.code in transient_codes and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"{provider} API returned HTTP {error.code}: {detail}") from error
            except URLError as error:
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"{provider} API connection failed: {error.reason}") from error
        raise RuntimeError(f"{provider} API request failed after retries")

    def _create_openai_response(self, prompt: str) -> dict[str, Any]:
        schema = self._article_schema()
        # OpenAI supports these extra constraints on non-fine-tuned models.
        schema["properties"]["title"].update({"minLength": 12, "maxLength": 100})
        schema["properties"]["subtitle"].update({"minLength": 20, "maxLength": 180})
        schema["properties"]["body_markdown"].update({"minLength": 1000})
        schema["properties"]["tags"]["items"]["maxLength"] = 25
        return self._json_request(
            "https://api.openai.com/v1/responses",
            {
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "medium-devops-bot/0.1",
            },
            {
                "model": self.config.openai_model,
                "input": [
                    {"role": "developer", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "reasoning": {"effort": "low"},
                "max_output_tokens": 6000,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "technical_article",
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
            "OpenAI",
        )

    def _create_gemini_response(self, prompt: str) -> dict[str, Any]:
        model = self.config.gemini_model
        return self._json_request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {
                "x-goog-api-key": self.config.gemini_api_key,
                "Content-Type": "application/json",
                "User-Agent": "medium-devops-bot/0.1",
            },
            {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.8,
                    "maxOutputTokens": 6000,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": self._article_schema(),
                },
            },
            "Gemini",
        )

    @staticmethod
    def _output_text(response: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(str(content["text"]))
                elif content.get("type") == "refusal":
                    raise RuntimeError(f"article generation was refused: {content.get('refusal', '')}")
        if not chunks:
            error = response.get("error") or response.get("incomplete_details") or "no output text"
            raise RuntimeError(f"OpenAI returned no article: {error}")
        return "".join(chunks)

    @staticmethod
    def _gemini_output_text(response: dict[str, Any]) -> str:
        chunks: list[str] = []
        for candidate in response.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("text"):
                    chunks.append(str(part["text"]))
        if not chunks:
            reason = response.get("promptFeedback") or "no candidate text"
            raise RuntimeError(f"Gemini returned no article: {reason}")
        return "".join(chunks)

    def generate(self, topic: str, previous_titles: list[str]) -> GeneratedArticle:
        recent = "\n".join(f"- {title}" for title in previous_titles[-30:]) or "- None yet"
        prompt = f"""Write today's article about this area: {topic}

Audience: intermediate DevOps, infrastructure, platform, and MLOps engineers.
Target length: {self.config.min_words}-{self.config.max_words} words.
Author voice: precise, approachable, opinionated when tradeoffs justify it.
Publication: {self.config.medium_publication_name or "an independent engineering blog"}.
Author: {self.config.author_name}.
Use 2-3 Medium tags; each tag must be at most 25 characters.

Do not substantially repeat these recent titles:
{recent}
"""
        if self.config.llm_provider == "gemini":
            response = self._create_gemini_response(prompt)
            output = self._gemini_output_text(response)
        else:
            response = self._create_openai_response(prompt)
            output = self._output_text(response)
        try:
            article = GeneratedArticle.from_dict(json.loads(output))
        except json.JSONDecodeError as error:
            raise RuntimeError("OpenAI returned malformed structured output") from error
        count = word_count(article.body_markdown)
        if not self.config.min_words <= count <= self.config.max_words:
            raise ValueError(
                f"generated article has {count} words; expected "
                f"{self.config.min_words}-{self.config.max_words}"
            )
        return article
