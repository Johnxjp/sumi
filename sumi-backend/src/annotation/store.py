"""Persist relevance judgments to annotations.json with atomic writes."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src.annotation.models import AnnotateRequest


def normalize_query(query: str) -> str:
    return " ".join(query.split()).casefold()


class AnnotationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "queries": {}}
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        fd, tmp_path = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    def get_for_query(self, query: str) -> dict[str, int]:
        data = self._load()
        entry = data["queries"].get(normalize_query(query))
        if entry is None:
            return {}
        return {key: ann["score"] for key, ann in entry["annotations"].items()}

    def upsert(self, req: AnnotateRequest) -> None:
        now = datetime.now(UTC).isoformat()
        data = self._load()
        query_key = normalize_query(req.query)
        entry = data["queries"].setdefault(
            query_key,
            {"query_text": req.query, "created_at": now, "annotations": {}},
        )
        annotation = entry["annotations"].get(req.chunk_key)
        created_at = annotation["created_at"] if annotation else now
        entry["annotations"][req.chunk_key] = {
            "score": req.score,
            "text": req.text,
            "metadata": req.metadata,
            "sources": [s.model_dump() for s in req.sources],
            "created_at": created_at,
            "updated_at": now,
        }
        self._save(data)
