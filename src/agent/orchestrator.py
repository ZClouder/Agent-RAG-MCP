"""Deterministic single-agent orchestration over the existing RAG tool."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from mcp import types

from src.agent.state import AgentResult, AgentState, ToolCallRecord
from src.core.trace import TraceCollector, TraceContext


QueryToolHandler = Callable[..., Awaitable[types.CallToolResult]]


class AgentExecutionError(RuntimeError):
    """Raised when the agent cannot complete a valid turn."""


class AgentOrchestrator:
    """Run one fail-fast Agent-RAG-Memory turn."""

    REQUIRED_STAGES = [
        "agent_start",
        "memory_retrieve",
        "tool_call",
        "answer_compose",
        "memory_write",
        "agent_finish",
    ]

    def __init__(
        self,
        query_tool_handler: QueryToolHandler,
        memory_manager: Any,
        trace_collector: Optional[TraceCollector] = None,
    ) -> None:
        if query_tool_handler is None:
            raise ValueError("query_tool_handler is required")
        if memory_manager is None:
            raise ValueError("memory_manager is required")
        self.query_tool_handler = query_tool_handler
        self.memory_manager = memory_manager
        self.trace_collector = trace_collector or TraceCollector()

    async def answer(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str,
        collection: str,
        top_k: int,
    ) -> AgentResult:
        self._validate_inputs(query, user_id, session_id, collection, top_k)

        state = AgentState(
            query=query.strip(),
            user_id=user_id.strip(),
            session_id=session_id.strip(),
            collection=collection.strip(),
            top_k=top_k,
        )
        trace = TraceContext(trace_type="agent")
        trace.metadata.update(
            {
                "query": state.query[:200],
                "user_id": state.user_id,
                "session_id": state.session_id,
                "collection": state.collection,
                "top_k": state.top_k,
            }
        )

        self._record(trace, "agent_start", {"success": True, "error": None, "input_count": 1, "output_count": 1})

        try:
            state.memory_contexts = self._retrieve_memory(state)
            self._record(
                trace,
                "memory_retrieve",
                {
                    "success": True,
                    "error": None,
                    "input_count": 1,
                    "output_count": len(state.memory_contexts),
                },
            )

            tool_result = await self._call_query_tool(state, trace)
            retrieval_text = self._text_from_tool_result(tool_result)
            state.citations = self._extract_citations(tool_result)
            if not state.citations:
                raise AgentExecutionError("query_knowledge_hub returned no citations")

            state.answer = self._compose_answer(state, retrieval_text)
            self._record(
                trace,
                "answer_compose",
                {
                    "success": True,
                    "error": None,
                    "input_count": len(state.citations),
                    "output_count": 1,
                },
            )

            memory_events = self._write_memory(state, trace)
            self._record(
                trace,
                "agent_finish",
                {
                    "success": True,
                    "error": None,
                    "input_count": 1,
                    "output_count": 1,
                },
            )
            self.trace_collector.collect(trace)

            return AgentResult(
                answer=state.answer,
                citations=state.citations,
                tool_calls=[call.to_dict() for call in state.tool_calls],
                memory_events=memory_events,
                trace_id=trace.trace_id,
            )
        except Exception as exc:
            self._record(
                trace,
                "agent_finish",
                {
                    "success": False,
                    "error": str(exc),
                    "input_count": 1,
                    "output_count": 0,
                },
            )
            self.trace_collector.collect(trace)
            raise

    def _retrieve_memory(self, state: AgentState) -> List[Dict[str, Any]]:
        records = self.memory_manager.retrieve(
            user_id=state.user_id,
            session_id=state.session_id,
            query=state.query,
            limit=5,
        )
        return [self._as_dict(record) for record in records]

    async def _call_query_tool(
        self,
        state: AgentState,
        trace: TraceContext,
    ) -> types.CallToolResult:
        arguments = {
            "query": state.query,
            "top_k": state.top_k,
            "collection": state.collection,
        }
        started = time.monotonic()
        result = await self.query_tool_handler(**arguments)
        elapsed_ms = (time.monotonic() - started) * 1000.0

        if result.isError:
            state.tool_calls.append(
                ToolCallRecord("query_knowledge_hub", arguments, False, elapsed_ms, 0)
            )
            self._record(
                trace,
                "tool_call",
                {
                    "success": False,
                    "error": self._text_from_tool_result(result),
                    "tool_name": "query_knowledge_hub",
                    "input_count": 1,
                    "output_count": 0,
                },
                elapsed_ms=elapsed_ms,
            )
            raise AgentExecutionError("query_knowledge_hub failed")

        citations = self._extract_citations(result)
        state.tool_calls.append(
            ToolCallRecord(
                "query_knowledge_hub",
                arguments,
                True,
                elapsed_ms,
                len(citations),
            )
        )
        self._record(
            trace,
            "tool_call",
            {
                "success": True,
                "error": None,
                "tool_name": "query_knowledge_hub",
                "input_count": 1,
                "output_count": len(citations),
            },
            elapsed_ms=elapsed_ms,
        )
        if not citations:
            raise AgentExecutionError("query_knowledge_hub returned zero results")
        return result

    def _write_memory(self, state: AgentState, trace: TraceContext) -> List[Dict[str, Any]]:
        events = self.memory_manager.write_from_turn(
            user_id=state.user_id,
            session_id=state.session_id,
            query=state.query,
            answer=state.answer,
            tool_calls=[call.to_dict() for call in state.tool_calls],
            citations=state.citations,
            trace_id=trace.trace_id,
        )
        event_dicts = [self._as_dict(event) for event in events]
        self._record(
            trace,
            "memory_write",
            {
                "success": True,
                "error": None,
                "input_count": 1,
                "output_count": len(event_dicts),
            },
        )
        if not event_dicts:
            raise AgentExecutionError("memory write produced no events")
        return event_dicts

    def _compose_answer(self, state: AgentState, retrieval_text: str) -> str:
        memory_note = ""
        if state.memory_contexts:
            memory_note = f"\n\nMemory contexts used: {len(state.memory_contexts)}"
        return (
            f"Answer grounded in {len(state.citations)} citations for query: {state.query}\n\n"
            f"{retrieval_text.strip()}"
            f"{memory_note}"
        )

    @staticmethod
    def _validate_inputs(
        query: str,
        user_id: str,
        session_id: str,
        collection: str,
        top_k: int,
    ) -> None:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")
        if not isinstance(collection, str) or not collection.strip():
            raise ValueError("collection is required")
        if not isinstance(top_k, int) or top_k < 1 or top_k > 20:
            raise ValueError("top_k must be an integer between 1 and 20")

    @staticmethod
    def _text_from_tool_result(result: types.CallToolResult) -> str:
        texts = [
            block.text
            for block in result.content
            if isinstance(block, types.TextContent)
        ]
        return "\n".join(texts).strip()

    @staticmethod
    def _extract_citations(result: types.CallToolResult) -> List[Dict[str, Any]]:
        text = AgentOrchestrator._text_from_tool_result(result)
        matches = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
        for raw_json in reversed(matches):
            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            citations = payload.get("citations")
            if isinstance(citations, list):
                return [item for item in citations if isinstance(item, dict)]
        return []

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            result = value.to_dict()
            if isinstance(result, dict):
                return result
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        raise TypeError(f"Cannot convert {type(value).__name__} to dict")

    @staticmethod
    def _record(
        trace: TraceContext,
        stage_name: str,
        data: Dict[str, Any],
        elapsed_ms: Optional[float] = None,
    ) -> None:
        if "success" not in data or "error" not in data:
            raise ValueError("agent trace stage data must include success and error")
        trace.record_stage(stage_name, data, elapsed_ms=elapsed_ms)
