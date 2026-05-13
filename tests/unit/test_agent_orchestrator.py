"""Tests for deterministic Agent orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from mcp import types

from src.agent import AgentExecutionError, AgentOrchestrator
from src.core.trace import TraceCollector


class FakeMemoryManager:
    def __init__(self) -> None:
        self.retrieve_calls: List[Dict[str, Any]] = []
        self.write_calls: List[Dict[str, Any]] = []
        self.records: List[Dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.retrieve_calls.append(kwargs)
        return list(self.records)

    def write_from_turn(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.write_calls.append(kwargs)
        return [{"event_type": "episodic_memory_written", "record_id": "mem-1"}]


def rag_result(*, citations: List[Dict[str, Any]], is_error: bool = False) -> types.CallToolResult:
    structured = {"citations": citations, "metadata": {"result_count": len(citations)}}
    text = (
        "Retrieved context\n\n"
        "---\n"
        "**References (JSON):**\n"
        "```json\n"
        f"{json.dumps(structured)}\n"
        "```"
    )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=is_error,
    )


@pytest.mark.asyncio
async def test_agent_success_writes_memory_and_trace(tmp_path: Path) -> None:
    memory = FakeMemoryManager()

    async def query_tool(**kwargs: Any) -> types.CallToolResult:
        assert kwargs == {"query": "What is RAG?", "top_k": 3, "collection": "docs"}
        return rag_result(citations=[{"id": "c1", "source": "doc.md"}])

    orchestrator = AgentOrchestrator(
        query_tool_handler=query_tool,
        memory_manager=memory,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )

    result = await orchestrator.answer(
        query="What is RAG?",
        user_id="u1",
        session_id="s1",
        collection="docs",
        top_k=3,
    )

    payload = result.to_dict()
    assert payload["answer"].startswith("Answer grounded in 1 citations")
    assert payload["citations"] == [{"id": "c1", "source": "doc.md"}]
    assert payload["tool_calls"][0]["tool_name"] == "query_knowledge_hub"
    assert payload["tool_calls"][0]["success"] is True
    assert payload["memory_events"] == [
        {"event_type": "episodic_memory_written", "record_id": "mem-1"}
    ]
    assert memory.retrieve_calls[0]["user_id"] == "u1"
    assert memory.write_calls[0]["trace_id"] == payload["trace_id"]

    trace_line = (tmp_path / "traces.jsonl").read_text(encoding="utf-8").strip()
    trace = json.loads(trace_line)
    assert trace["trace_type"] == "agent"
    assert [stage["stage"] for stage in trace["stages"]] == [
        "agent_start",
        "memory_retrieve",
        "tool_call",
        "answer_compose",
        "memory_write",
        "agent_finish",
    ]


@pytest.mark.asyncio
async def test_agent_fails_on_empty_query(tmp_path: Path) -> None:
    async def query_tool(**kwargs: Any) -> types.CallToolResult:
        raise AssertionError("tool should not be called")

    orchestrator = AgentOrchestrator(
        query_tool_handler=query_tool,
        memory_manager=FakeMemoryManager(),
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )

    with pytest.raises(ValueError, match="query is required"):
        await orchestrator.answer(
            query=" ",
            user_id="u1",
            session_id="s1",
            collection="docs",
            top_k=3,
        )


@pytest.mark.asyncio
async def test_agent_fails_on_tool_error(tmp_path: Path) -> None:
    memory = FakeMemoryManager()

    async def query_tool(**kwargs: Any) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="tool failed")],
            isError=True,
        )

    orchestrator = AgentOrchestrator(
        query_tool_handler=query_tool,
        memory_manager=memory,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )

    with pytest.raises(AgentExecutionError, match="query_knowledge_hub failed"):
        await orchestrator.answer(
            query="What is RAG?",
            user_id="u1",
            session_id="s1",
            collection="docs",
            top_k=3,
        )
    assert memory.write_calls == []


@pytest.mark.asyncio
async def test_agent_fails_on_missing_citations(tmp_path: Path) -> None:
    memory = FakeMemoryManager()

    async def query_tool(**kwargs: Any) -> types.CallToolResult:
        return rag_result(citations=[])

    orchestrator = AgentOrchestrator(
        query_tool_handler=query_tool,
        memory_manager=memory,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )

    with pytest.raises(AgentExecutionError, match="zero results"):
        await orchestrator.answer(
            query="What is RAG?",
            user_id="u1",
            session_id="s1",
            collection="docs",
            top_k=3,
        )
    assert memory.write_calls == []
