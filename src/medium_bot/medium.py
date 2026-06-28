from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import Config
from .models import Draft


@dataclass(frozen=True)
class PublishResult:
    url: str
    post_id: str
    status: str


class MediumClient:
    """Small client for Medium's legacy API, for existing tokens only."""

    base_url = "https://api.medium.com/v1"

    def __init__(self, config: Config):
        if not config.medium_access_token:
            raise ValueError(
                "MEDIUM_ACCESS_TOKEN is required. Medium no longer issues new integration tokens."
            )
        self.config = config

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.medium_access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "User-Agent": "medium-devops-bot/0.1 (human-approved publishing)",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Medium API returned HTTP {error.code}: {detail}") from error

    def publish(self, draft: Draft, status: str = "public") -> PublishResult:
        if status not in {"public", "draft", "unlisted"}:
            raise ValueError("status must be public, draft, or unlisted")
        payload = {
            "title": draft.title,
            "contentFormat": "markdown",
            "content": draft.content,
            "tags": draft.tags[:3],
            "publishStatus": status,
        }
        publication_id = self.config.medium_publication_id
        profile: dict[str, Any] | None = None
        if not publication_id and self.config.medium_publication_slug:
            profile = self._request("GET", "/me")
            author_id = str(profile["data"]["id"])
            publications = self._request("GET", f"/users/{author_id}/publications").get("data", [])
            slug = self.config.medium_publication_slug.casefold().strip("/")
            for publication in publications:
                url = str(publication.get("url", "")).casefold().rstrip("/")
                name = str(publication.get("name", "")).casefold().replace("_", "-").replace(" ", "-")
                if url.endswith(f"/{slug}") or name == slug:
                    publication_id = str(publication["id"])
                    break
            if not publication_id:
                raise RuntimeError(
                    f"Medium publication {self.config.medium_publication_slug!r} was not found "
                    "among the authenticated user's publications"
                )
        if publication_id:
            path = f"/publications/{publication_id}/posts"
        else:
            profile = profile or self._request("GET", "/me")
            author_id = profile["data"]["id"]
            path = f"/users/{author_id}/posts"
        result = self._request("POST", path, payload)["data"]
        return PublishResult(
            url=str(result.get("url", "")),
            post_id=str(result.get("id", "")),
            status=str(result.get("publishStatus", status)),
        )
