"""SQLite-backed episodic memory for successful conversation turns."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.memory.cards import MemoryCard, MemoryCardStore, MemoryExtractor

JSONDict = dict[str, Any]
JSONList = list[Any]


@dataclass(frozen=True)
class MemoryEvent:
    """Input event for one successful turn."""

    user_id: str
    session_id: str
    query: str
    answer: str
    id: str | None = None
    metadata: JSONDict = field(default_factory=dict)
    tool_calls: JSONList = field(default_factory=list)
    citations: JSONList = field(default_factory=list)
    created_at: str | None = None


@dataclass(frozen=True)
class MemoryRecord:
    """Persisted episodic memory record."""

    id: str
    user_id: str
    session_id: str
    query: str
    answer: str
    metadata: JSONDict = field(default_factory=dict)
    tool_calls: JSONList = field(default_factory=list)
    citations: JSONList = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())
    sequence: int | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(name: str, value: str) -> None:
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


class EpisodicMemoryStore:
    """Persistent SQLite store for episodic memories.

    Records are isolated by ``user_id`` and ``session_id``. Rewriting the same
    record ID with identical payload is idempotent; rewriting it with different
    payload raises ``ValueError``.
    """

    def __init__(self, db_path: str = "data/db/episodic_memory.db") -> None:
        self.db_path = db_path
        self._ensure_database()

    def close(self) -> None:
        """Kept for API symmetry; connections are short-lived."""

    def append(self, event: MemoryEvent) -> MemoryRecord:
        """Persist one successful turn event."""
        record = MemoryRecord(
            id=event.id or str(uuid4()),
            user_id=event.user_id,
            session_id=event.session_id,
            query=event.query,
            answer=event.answer,
            metadata=event.metadata,
            tool_calls=event.tool_calls,
            citations=event.citations,
            created_at=event.created_at or _utc_now(),
        )
        return self.write(record)

    def write(self, record: MemoryRecord) -> MemoryRecord:
        """Persist a memory record and return the stored record."""
        self._validate_record(record)
        metadata_json = _json_dumps("metadata", record.metadata)
        tool_calls_json = _json_dumps("tool_calls", record.tool_calls)
        citations_json = _json_dumps("citations", record.citations)

        existing = self.get(record.id)
        if existing is not None:
            if self._same_payload(
                existing,
                record,
                metadata_json,
                tool_calls_json,
                citations_json,
            ):
                return existing
            raise ValueError(f"memory id already exists with different payload: {record.id}")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO episodic_memories (
                    id,
                    user_id,
                    session_id,
                    query,
                    answer,
                    metadata_json,
                    tool_calls_json,
                    citations_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.user_id,
                    record.session_id,
                    record.query,
                    record.answer,
                    metadata_json,
                    tool_calls_json,
                    citations_json,
                    record.created_at,
                ),
            )
            conn.commit()
            sequence = int(cursor.lastrowid)
        finally:
            conn.close()

        return MemoryRecord(
            id=record.id,
            user_id=record.user_id,
            session_id=record.session_id,
            query=record.query,
            answer=record.answer,
            metadata=record.metadata,
            tool_calls=record.tool_calls,
            citations=record.citations,
            created_at=record.created_at,
            sequence=sequence,
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Return a record by ID, or ``None`` when absent."""
        _require_text("id", memory_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM episodic_memories WHERE id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def list(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """List memories for one user/session in write order."""
        _require_text("user_id", user_id)
        _require_text("session_id", session_id)
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        query = """
            SELECT *
            FROM episodic_memories
            WHERE user_id = ? AND session_id = ?
            ORDER BY sequence ASC
        """
        params: list[Any] = [user_id, session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _ensure_database(self) -> None:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    tool_calls_json TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episodic_user_session_sequence
                ON episodic_memories(user_id, session_id, sequence)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _validate_record(self, record: MemoryRecord) -> None:
        _require_text("id", record.id)
        _require_text("user_id", record.user_id)
        _require_text("session_id", record.session_id)
        _require_text("query", record.query)
        _require_text("answer", record.answer)
        _require_text("created_at", record.created_at)

    def _same_payload(
        self,
        existing: MemoryRecord,
        record: MemoryRecord,
        metadata_json: str,
        tool_calls_json: str,
        citations_json: str,
    ) -> bool:
        return (
            existing.user_id == record.user_id
            and existing.session_id == record.session_id
            and existing.query == record.query
            and existing.answer == record.answer
            and _json_dumps("metadata", existing.metadata) == metadata_json
            and _json_dumps("tool_calls", existing.tool_calls) == tool_calls_json
            and _json_dumps("citations", existing.citations) == citations_json
        )

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            query=row["query"],
            answer=row["answer"],
            metadata=_json_loads(row["metadata_json"]),
            tool_calls=_json_loads(row["tool_calls_json"]),
            citations=_json_loads(row["citations_json"]),
            created_at=row["created_at"],
            sequence=row["sequence"],
        )


class MemoryManager:
    """High-level episodic memory API used by RAG callers."""

    def __init__(
        self,
        db_path: str = "data/db/episodic_memory.db",
        store: EpisodicMemoryStore | None = None,
        card_store: MemoryCardStore | None = None,
        extractor: MemoryExtractor | None = None,
        project_id: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.store = store or EpisodicMemoryStore(db_path=db_path)
        self.card_store = card_store or MemoryCardStore(db_path=db_path)
        self.extractor = extractor or MemoryExtractor()
        self.project_id = project_id

    def write_turn(
        self,
        user_id: str,
        session_id: str,
        query: str,
        answer: str,
        metadata: JSONDict | None = None,
        tool_calls: JSONList | None = None,
        citations: JSONList | None = None,
        memory_id: str | None = None,
        created_at: str | None = None,
    ) -> MemoryRecord:
        """Write one successful conversation turn."""
        event = MemoryEvent(
            id=memory_id,
            user_id=user_id,
            session_id=session_id,
            query=query,
            answer=answer,
            metadata=metadata if metadata is not None else {},
            tool_calls=tool_calls if tool_calls is not None else [],
            citations=citations if citations is not None else [],
            created_at=created_at,
        )
        return self.store.append(event)

    def add_event(self, event: MemoryEvent) -> MemoryRecord:
        """Persist a pre-built event."""
        return self.store.append(event)

    def write_from_turn(
        self,
        user_id: str,
        session_id: str,
        query: str,
        answer: str,
        tool_calls: JSONList,
        citations: JSONList,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        """Write one successful agent turn and return agent-facing events."""
        record = self.write_turn(
            user_id=user_id,
            session_id=session_id,
            query=query,
            answer=answer,
            metadata={"trace_id": trace_id},
            tool_calls=tool_calls,
            citations=citations,
        )
        events = [
            {
                "event_type": "episodic_memory_written",
                "record_id": record.id,
                "trace_id": trace_id,
                "user_id": record.user_id,
                "session_id": record.session_id,
            }
        ]
        for card in self.extractor.extract_from_turn(
            user_id=user_id,
            session_id=session_id,
            query=query,
            answer=answer,
            evidence_id=record.id,
            project_id=self.project_id,
        ):
            stored_card = self.card_store.upsert(card)
            events.append(
                {
                    "event_type": "memory_card_upserted",
                    "card_id": stored_card.id,
                    "card_type": stored_card.card_type,
                    "trace_id": trace_id,
                    "user_id": stored_card.user_id,
                    "session_id": stored_card.session_id,
                }
            )
        return events

    def retrieve(
        self,
        user_id: str,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[MemoryRecord | MemoryCard]:
        """Retrieve compact Agent memory context for one user/session."""
        _require_text("query", query)
        if limit <= 0:
            raise ValueError("limit must be positive")

        cards = self.card_store.search(
            user_id=user_id,
            session_id=session_id,
            project_id=self.project_id,
            query=query,
            limit=limit,
        )
        remaining = max(0, limit - len(cards))
        if remaining == 0:
            return cards

        history = self.get_history(user_id=user_id, session_id=session_id)
        recent_history = history[-remaining:]
        return [*cards, *recent_history]

    def upsert_card(self, card: MemoryCard) -> MemoryCard:
        """Create or update one structured memory card."""
        return self.card_store.upsert(card)

    def retrieve_cards(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        project_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryCard]:
        """Retrieve structured memory cards for a query."""
        return self.card_store.search(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id if project_id is not None else self.project_id,
            query=query,
            limit=limit,
        )

    def list_cards(
        self,
        user_id: str,
        session_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryCard]:
        """List active structured memory cards."""
        return self.card_store.list(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id if project_id is not None else self.project_id,
            limit=limit,
        )

    def record_turn(self, *args: Any, **kwargs: Any) -> MemoryRecord:
        """Alias for ``write_turn``."""
        return self.write_turn(*args, **kwargs)

    def get_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Read memories for one user/session."""
        return self.store.list(user_id=user_id, session_id=session_id, limit=limit)

    def list_memories(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Alias for ``get_history``."""
        return self.get_history(user_id=user_id, session_id=session_id, limit=limit)

    def close(self) -> None:
        self.store.close()
        self.card_store.close()
