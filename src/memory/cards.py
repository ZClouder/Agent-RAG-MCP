"""Structured long-term memory cards for content-operations Agent context."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JSONList = list[Any]

CARD_TYPES = {"preference", "workflow", "compliance", "evaluation"}
CARD_STATUSES = {"active", "archived", "needs_review"}

SECRET_PATTERNS = (
    re.compile(r"\b(api[_-]?key|secret|token|password|passwd|private[_-]?key)\b", re.I),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(name: str, value: str | None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _json_dumps(name: str, value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be JSON serializable") from exc


def _json_loads(value: str) -> Any:
    return json.loads(value)


def _clamp_score(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    if math.isnan(float(value)) or math.isinf(float(value)):
        raise ValueError(f"{name} must be finite")
    return max(0.0, min(1.0, float(value)))


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in WORD_PATTERN.findall(text or "")}


def _stable_card_id(user_id: str, card_type: str, title: str, project_id: str | None) -> str:
    raw = f"{user_id.strip()}:{project_id or ''}:{card_type}:{title.strip().lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"card-{digest[:16]}"


@dataclass(frozen=True)
class MemoryCard:
    """Curated long-term memory used for small high-signal Agent injection."""

    user_id: str
    card_type: str
    title: str
    description: str
    content: str
    id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    importance: float = 0.6
    confidence: float = 0.8
    source: str = "auto"
    evidence_ids: JSONList = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    last_accessed_at: str | None = None
    pinned: bool = False
    status: str = "active"
    sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "card_type": self.card_type,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "importance": self.importance,
            "confidence": self.confidence,
            "source": self.source,
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed_at": self.last_accessed_at,
            "pinned": self.pinned,
            "status": self.status,
            "sequence": self.sequence,
        }


class MemoryCardStore:
    """SQLite store for structured memory cards."""

    def __init__(self, db_path: str = "data/db/episodic_memory.db") -> None:
        self.db_path = db_path
        self._ensure_database()

    def close(self) -> None:
        """Kept for API symmetry; connections are short-lived."""

    def upsert(self, card: MemoryCard) -> MemoryCard:
        """Create or update a structured memory card."""
        self._validate_card(card)
        now = _utc_now()
        card_id = card.id or _stable_card_id(
            user_id=card.user_id,
            card_type=card.card_type,
            title=card.title,
            project_id=card.project_id,
        )
        existing = self.get(card_id)
        created_at = existing.created_at if existing else (card.created_at or now)
        updated_at = card.updated_at or now
        last_accessed_at = card.last_accessed_at or (
            existing.last_accessed_at if existing else updated_at
        )
        evidence_ids = self._merge_evidence(
            existing.evidence_ids if existing else [],
            card.evidence_ids,
        )

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO memory_cards (
                    id,
                    user_id,
                    session_id,
                    project_id,
                    card_type,
                    title,
                    description,
                    content,
                    importance,
                    confidence,
                    source,
                    evidence_ids_json,
                    created_at,
                    updated_at,
                    last_accessed_at,
                    pinned,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    project_id = excluded.project_id,
                    description = excluded.description,
                    content = excluded.content,
                    importance = excluded.importance,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    evidence_ids_json = excluded.evidence_ids_json,
                    updated_at = excluded.updated_at,
                    last_accessed_at = excluded.last_accessed_at,
                    pinned = excluded.pinned,
                    status = excluded.status
                """,
                (
                    card_id,
                    card.user_id,
                    card.session_id,
                    card.project_id,
                    card.card_type,
                    card.title,
                    card.description,
                    card.content,
                    _clamp_score("importance", card.importance),
                    _clamp_score("confidence", card.confidence),
                    card.source,
                    _json_dumps("evidence_ids", evidence_ids),
                    created_at,
                    updated_at,
                    last_accessed_at,
                    1 if card.pinned else 0,
                    card.status,
                ),
            )
            conn.commit()
            sequence = cursor.lastrowid if existing is None else existing.sequence
        finally:
            conn.close()

        stored = self.get(card_id)
        if stored is None:
            raise RuntimeError(f"failed to upsert memory card: {card_id}")
        if sequence is not None and stored.sequence is None:
            return MemoryCard(**{**stored.to_dict(), "sequence": int(sequence)})
        return stored

    def get(self, card_id: str) -> MemoryCard | None:
        _require_text("id", card_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM memory_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            return self._row_to_card(row) if row else None
        finally:
            conn.close()

    def list(
        self,
        user_id: str,
        session_id: str | None = None,
        project_id: str | None = None,
        status: str = "active",
        limit: int | None = None,
    ) -> list[MemoryCard]:
        _require_text("user_id", user_id)
        if status not in CARD_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(CARD_STATUSES))}")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        query = """
            SELECT *
            FROM memory_cards
            WHERE user_id = ? AND status = ?
        """
        params: list[Any] = [user_id, status]
        if session_id is not None:
            query += " AND (session_id = ? OR session_id IS NULL)"
            params.append(session_id)
        if project_id is not None:
            query += " AND (project_id = ? OR project_id IS NULL)"
            params.append(project_id)
        query += " ORDER BY pinned DESC, updated_at DESC, sequence DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_card(row) for row in rows]
        finally:
            conn.close()

    def search(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        project_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryCard]:
        _require_text("query", query)
        if limit <= 0:
            raise ValueError("limit must be positive")

        candidates = self.list(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            status="active",
            limit=None,
        )
        query_tokens = _tokens(query)
        scored = [
            (self._score_card(card, query_tokens), card)
            for card in candidates
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = [card for score, card in scored if score > 0.0][:limit]
        self._touch([card.id for card in hits if card.id])
        return hits

    def _ensure_database(self) -> None:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_cards (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    project_id TEXT,
                    card_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_cards_user_status
                ON memory_cards(user_id, status, updated_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_cards_user_session
                ON memory_cards(user_id, session_id, status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_cards_user_project
                ON memory_cards(user_id, project_id, status)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _validate_card(self, card: MemoryCard) -> None:
        _require_text("user_id", card.user_id)
        _require_text("card_type", card.card_type)
        _require_text("title", card.title)
        _require_text("description", card.description)
        _require_text("content", card.content)
        _require_text("source", card.source)
        if card.card_type not in CARD_TYPES:
            raise ValueError(f"card_type must be one of: {', '.join(sorted(CARD_TYPES))}")
        if card.status not in CARD_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(CARD_STATUSES))}")
        _clamp_score("importance", card.importance)
        _clamp_score("confidence", card.confidence)
        _json_dumps("evidence_ids", card.evidence_ids)

    @staticmethod
    def _merge_evidence(existing: JSONList, new: JSONList) -> JSONList:
        merged: JSONList = []
        for value in [*existing, *new]:
            if value not in merged:
                merged.append(value)
        return merged

    @staticmethod
    def _score_card(card: MemoryCard, query_tokens: set[str]) -> float:
        text = " ".join([card.title, card.description, card.content, card.card_type])
        card_tokens = _tokens(text)
        if not card_tokens:
            relevance = 0.0
        else:
            overlap = len(query_tokens & card_tokens)
            relevance = overlap / max(1, len(query_tokens))
        pinned_bonus = 0.15 if card.pinned else 0.0
        return (
            0.55 * relevance
            + 0.2 * card.importance
            + 0.15 * card.confidence
            + pinned_bonus
        )

    def _touch(self, card_ids: list[str]) -> None:
        if not card_ids:
            return
        placeholders = ",".join("?" for _ in card_ids)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                f"UPDATE memory_cards SET last_accessed_at = ? WHERE id IN ({placeholders})",
                [_utc_now(), *card_ids],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> MemoryCard:
        return MemoryCard(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            card_type=row["card_type"],
            title=row["title"],
            description=row["description"],
            content=row["content"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            source=row["source"],
            evidence_ids=_json_loads(row["evidence_ids_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            pinned=bool(row["pinned"]),
            status=row["status"],
            sequence=row["sequence"],
        )


class MemoryExtractor:
    """Conservative rule-based extractor for content-operations memory cards."""

    def extract_from_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        answer: str,
        evidence_id: str,
        project_id: str | None = None,
    ) -> list[MemoryCard]:
        _require_text("user_id", user_id)
        _require_text("session_id", session_id)
        _require_text("query", query)
        _require_text("answer", answer)
        _require_text("evidence_id", evidence_id)

        if self._contains_secret(query) or self._contains_secret(answer):
            return []
        if not self._is_memory_intent(query):
            return []

        card_type = self._classify(query)
        title = self._title_for(card_type, query)
        description = self._description_for(card_type, query)
        return [
            MemoryCard(
                user_id=user_id,
                session_id=session_id,
                project_id=project_id,
                card_type=card_type,
                title=title,
                description=description,
                content=query.strip(),
                importance=self._importance_for(card_type),
                confidence=0.85,
                source="auto_extracted_turn",
                evidence_ids=[evidence_id],
                pinned=card_type in {"preference", "compliance"},
            )
        ]

    @staticmethod
    def _contains_secret(text: str) -> bool:
        return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)

    @staticmethod
    def _is_memory_intent(text: str) -> bool:
        lower = (text or "").lower()
        markers = ("remember", "记住", "请记住", "以后", "下次")
        return any(marker in lower for marker in markers)

    @staticmethod
    def _classify(text: str) -> str:
        lower = (text or "").lower()
        if any(term in lower for term in ("评测", "评估", "query", "召回", "准确率")):
            return "evaluation"
        if any(term in lower for term in ("合规", "风险", "品牌规范", "禁用", "必须引用")):
            return "compliance"
        if any(
            term in lower
            for term in (
                "产品信息核查",
                "内容选题",
                "脚本",
                "复盘",
                "运营",
                "工作流",
            )
        ):
            return "workflow"
        return "preference"

    @staticmethod
    def _title_for(card_type: str, text: str) -> str:
        titles = {
            "preference": "Operator answer preference",
            "workflow": "Content-operations workflow context",
            "compliance": "Content compliance focus",
            "evaluation": "Offline evaluation feedback",
        }
        return titles[card_type]

    @staticmethod
    def _description_for(card_type: str, text: str) -> str:
        cleaned = " ".join((text or "").strip().split())
        if len(cleaned) > 180:
            cleaned = f"{cleaned[:177]}..."
        return cleaned

    @staticmethod
    def _importance_for(card_type: str) -> float:
        return {
            "preference": 0.8,
            "workflow": 0.75,
            "compliance": 0.9,
            "evaluation": 0.7,
        }[card_type]
