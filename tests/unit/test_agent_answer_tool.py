"""Tests for the agent_answer MCP tool."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agent.state import AgentResult
from src.mcp_server.protocol_handler import ProtocolHandler
from src.mcp_server.tools.agent_answer import (
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    agent_answer_handler,
    register_tool,
    set_orchestrator_for_testing,
)


class FakeOrchestrator:
    async def answer(self, **kwargs: Any) -> AgentResult:
        return AgentResult(
            answer=f"answer for {kwargs['query']}",
            citations=[{"id": "c1"}],
            tool_calls=[{"tool_name": "query_knowledge_hub", "success": True}],
            memory_events=[{"event_type": "episodic_memory_written"}],
            trace_id="trace-1",
        )


class FailingOrchestrator:
    async def answer(self, **kwargs: Any) -> AgentResult:
        raise RuntimeError("boom")


def teardown_function() -> None:
    set_orchestrator_for_testing(None)


def test_schema_requires_hard_inputs() -> None:
    assert TOOL_NAME == "agent_answer"
    assert TOOL_INPUT_SCHEMA["required"] == [
        "query",
        "user_id",
        "session_id",
        "collection",
        "top_k",
    ]
    assert TOOL_INPUT_SCHEMA["properties"]["top_k"]["minimum"] == 1
    assert TOOL_INPUT_SCHEMA["properties"]["top_k"]["maximum"] == 20


@pytest.mark.asyncio
async def test_handler_returns_structured_agent_result() -> None:
    set_orchestrator_for_testing(FakeOrchestrator())  # type: ignore[arg-type]

    result = await agent_answer_handler(
        query="What is RAG?",
        user_id="u1",
        session_id="s1",
        collection="docs",
        top_k=5,
    )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["answer"] == "answer for What is RAG?"
    assert payload["citations"] == [{"id": "c1"}]
    assert payload["trace_id"] == "trace-1"


@pytest.mark.asyncio
async def test_handler_returns_mcp_error_on_failure() -> None:
    set_orchestrator_for_testing(FailingOrchestrator())  # type: ignore[arg-type]

    result = await agent_answer_handler(
        query="What is RAG?",
        user_id="u1",
        session_id="s1",
        collection="docs",
        top_k=5,
    )

    assert result.isError is True
    assert "agent_answer failed: boom" in result.content[0].text


def test_register_tool_registers_agent_answer() -> None:
    handler = ProtocolHandler("test", "1")

    register_tool(handler)

    assert TOOL_NAME in handler.tools
    assert handler.tools[TOOL_NAME].input_schema is TOOL_INPUT_SCHEMA
