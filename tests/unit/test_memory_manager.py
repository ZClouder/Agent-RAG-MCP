"""Unit tests for v1 episodic memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.memory import (
    EpisodicMemoryStore,
    MemoryCard,
    MemoryCardStore,
    MemoryEvent,
    MemoryManager,
    MemoryRecord,
)


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
    assert MemoryCard is not None
    assert MemoryCardStore is not None
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
    MemoryCardStore(db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'episodic_memories'
            """
        ).fetchone()
        card_table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_cards'
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
    assert card_table is not None
    assert index is not None


def test_memory_card_upsert_and_search(manager: MemoryManager) -> None:
    card = manager.upsert_card(
        MemoryCard(
            user_id="u1",
            session_id="s1",
            card_type="compliance",
            title="Script compliance focus",
            description="Script compliance answers must include risk points and source docs.",
            content="For script compliance, cite brand guidelines and provide revision advice.",
            importance=0.9,
            confidence=0.9,
            evidence_ids=["turn-1"],
            pinned=True,
        )
    )

    hits = manager.retrieve_cards("u1", "脚本合规 风险 品牌规范", session_id="s1")

    assert hits[0].id == card.id
    assert hits[0].card_type == "compliance"
    assert hits[0].evidence_ids == ["turn-1"]


def test_memory_card_upsert_is_idempotent_and_merges_evidence(
    manager: MemoryManager,
) -> None:
    first = manager.upsert_card(
        MemoryCard(
            user_id="u1",
            session_id="s1",
            card_type="workflow",
            title="Content operations workflow",
            description="Product verification and topic ideation are recurring workflows.",
            content="Content ops users often check product facts and choose topics.",
            evidence_ids=["turn-1"],
        )
    )
    second = manager.upsert_card(
        MemoryCard(
            user_id="u1",
            session_id="s1",
            card_type="workflow",
            title="Content operations workflow",
            description="Product verification and topic ideation are recurring workflows.",
            content="Content ops users often check product facts and choose topics.",
            evidence_ids=["turn-2"],
        )
    )

    assert second.id == first.id
    assert second.evidence_ids == ["turn-1", "turn-2"]
    assert len(manager.list_cards("u1", session_id="s1")) == 1


def test_write_from_turn_extracts_business_memory_card(manager: MemoryManager) -> None:
    events = manager.write_from_turn(
        user_id="u1",
        session_id="s1",
        query="请记住：以后脚本合规问题优先给风险点、引用依据和修改建议。",
        answer="已记录。",
        tool_calls=[],
        citations=[],
        trace_id="trace-1",
    )

    assert [event["event_type"] for event in events] == [
        "episodic_memory_written",
        "memory_card_upserted",
    ]
    cards = manager.list_cards("u1", session_id="s1")
    assert len(cards) == 1
    assert cards[0].card_type == "compliance"
    assert cards[0].evidence_ids == [events[0]["record_id"]]


def test_write_from_turn_does_not_extract_plain_business_question(
    manager: MemoryManager,
) -> None:
    events = manager.write_from_turn(
        user_id="u1",
        session_id="s1",
        query="这款新品的核心卖点有哪些？",
        answer="请参考产品资料。",
        tool_calls=[],
        citations=[{"source": "product.md"}],
        trace_id="trace-1",
    )

    assert [event["event_type"] for event in events] == ["episodic_memory_written"]
    assert manager.list_cards("u1", session_id="s1") == []


def test_secret_like_turn_is_not_extracted(manager: MemoryManager) -> None:
    events = manager.write_from_turn(
        user_id="u1",
        session_id="s1",
        query="请记住我的 API key 是 sk-abcdefghijklmnopqrstuvwxyz",
        answer="不会记录密钥。",
        tool_calls=[],
        citations=[],
        trace_id="trace-1",
    )

    assert [event["event_type"] for event in events] == ["episodic_memory_written"]
    assert manager.list_cards("u1", session_id="s1") == []


def test_retrieve_limits_to_five_contexts(manager: MemoryManager) -> None:
    for index in range(8):
        manager.upsert_card(
            MemoryCard(
                user_id="u1",
                session_id="s1",
                card_type="workflow",
                title=f"Workflow {index}",
                description="产品信息核查 内容选题 脚本合规 复盘优化",
                content="运营检索场景",
            )
        )

    contexts = manager.retrieve(
        user_id="u1",
        session_id="s1",
        query="产品信息核查 内容选题 脚本合规",
        limit=5,
    )

    assert len(contexts) == 5
    assert all(isinstance(context, MemoryCard) for context in contexts)
