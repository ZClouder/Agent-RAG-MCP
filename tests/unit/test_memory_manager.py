"""Unit tests for v1 episodic memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.memory import EpisodicMemoryStore, MemoryEvent, MemoryManager, MemoryRecord


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "memory.db")


@pytest.fixture()
def manager(db_path: str) -> MemoryManager:
    mgr = MemoryManager(db_path=db_path)
    yield mgr
    mgr.close()


def test_exports_required_classes() -> None:
    assert MemoryRecord is not None
    assert MemoryEvent is not None
    assert EpisodicMemoryStore is not None
    assert MemoryManager is not None


def test_write_successful_turn(manager: MemoryManager) -> None:
    record = manager.write_turn(
        user_id="user-1",
        session_id="session-1",
        query="What is RAG?",
        answer="Retrieval augmented generation.",
        metadata={"model": "test"},
        tool_calls=[{"name": "search", "args": {"q": "RAG"}}],
        citations=[{"source": "doc-1"}],
        memory_id="turn-1",
    )

    assert record.id == "turn-1"
    assert record.user_id == "user-1"
    assert record.session_id == "session-1"
    assert record.metadata == {"model": "test"}
    assert record.tool_calls == [{"name": "search", "args": {"q": "RAG"}}]
    assert record.citations == [{"source": "doc-1"}]
    assert record.sequence == 1


def test_read_history_returns_write_order(manager: MemoryManager) -> None:
    manager.write_turn("u1", "s1", "q1", "a1", memory_id="m1")
    manager.write_turn("u1", "s1", "q2", "a2", memory_id="m2")
    manager.write_turn("u1", "s1", "q3", "a3", memory_id="m3")

    history = manager.get_history("u1", "s1")

    assert [record.id for record in history] == ["m1", "m2", "m3"]
    assert [record.query for record in history] == ["q1", "q2", "q3"]


def test_history_is_isolated_by_user_and_session(manager: MemoryManager) -> None:
    manager.write_turn("u1", "s1", "q1", "a1", memory_id="u1-s1")
    manager.write_turn("u1", "s2", "q2", "a2", memory_id="u1-s2")
    manager.write_turn("u2", "s1", "q3", "a3", memory_id="u2-s1")

    history = manager.get_history("u1", "s1")

    assert [record.id for record in history] == ["u1-s1"]


def test_records_persist_after_reopen(db_path: str) -> None:
    first = MemoryManager(db_path=db_path)
    first.write_turn("u1", "s1", "q1", "a1", memory_id="persisted")
    first.close()

    second = MemoryManager(db_path=db_path)
    try:
        history = second.get_history("u1", "s1")
    finally:
        second.close()

    assert len(history) == 1
    assert history[0].id == "persisted"
    assert history[0].query == "q1"


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("user_id", {"user_id": "", "session_id": "s1", "query": "q", "answer": "a"}),
        ("session_id", {"user_id": "u1", "session_id": "", "query": "q", "answer": "a"}),
        ("query", {"user_id": "u1", "session_id": "s1", "query": "", "answer": "a"}),
        ("answer", {"user_id": "u1", "session_id": "s1", "query": "q", "answer": ""}),
    ],
)
def test_write_turn_fails_fast_when_required_input_missing(
    manager: MemoryManager,
    field: str,
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match=f"{field} is required"):
        manager.write_turn(**kwargs)


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("metadata", {"metadata": {"bad": {1, 2}}}),
        ("metadata", {"metadata": set()}),
        ("tool_calls", {"tool_calls": [{"bad": {1, 2}}]}),
        ("citations", {"citations": [{"bad": {1, 2}}]}),
    ],
)
def test_json_fields_must_be_serializable(
    manager: MemoryManager,
    field: str,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match=f"{field} must be JSON serializable"):
        manager.write_turn("u1", "s1", "q", "a", **kwargs)


def test_same_id_same_payload_is_idempotent(manager: MemoryManager) -> None:
    first = manager.write_turn("u1", "s1", "q", "a", memory_id="same")
    second = manager.write_turn("u1", "s1", "q", "a", memory_id="same")

    assert second == first
    assert len(manager.get_history("u1", "s1")) == 1


def test_same_id_conflicting_payload_raises(manager: MemoryManager) -> None:
    manager.write_turn("u1", "s1", "q", "a", memory_id="same")

    with pytest.raises(ValueError, match="different payload"):
        manager.write_turn("u1", "s1", "q", "changed", memory_id="same")


def test_store_add_event_and_limit(db_path: str) -> None:
    store = EpisodicMemoryStore(db_path=db_path)
    store.append(MemoryEvent("u1", "s1", "q1", "a1", id="m1"))
    store.append(MemoryEvent("u1", "s1", "q2", "a2", id="m2"))

    records = store.list("u1", "s1", limit=1)

    assert [record.id for record in records] == ["m1"]


def test_database_schema_created(db_path: str) -> None:
    EpisodicMemoryStore(db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'episodic_memories'
            """
        ).fetchone()
        index = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_episodic_user_session_sequence'
            """
        ).fetchone()
    finally:
        conn.close()

    assert table is not None
    assert index is not None
