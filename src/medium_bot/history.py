from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class History:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"history must be a JSON list: {self.path}")
        return data

    def save(self, entries: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="history-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entries, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def for_date(self, date_string: str) -> dict[str, object] | None:
        return next((item for item in reversed(self.load()) if item.get("date") == date_string), None)

    def record(self, entry: dict[str, object]) -> None:
        entries = self.load()
        entries = [item for item in entries if item.get("date") != entry.get("date")]
        entries.append(entry)
        self.save(entries)
    def mark_published(self, path: Path, url: str, status: str) -> None:
        entries = self.load()
        found = False
        for entry in entries:
            if Path(str(entry.get("path", ""))).resolve() == path.resolve():
                entry["status"] = status
                entry["url"] = url
                found = True
        if not found:
            raise ValueError(f"draft is not tracked in history: {path}")
        self.save(entries)
