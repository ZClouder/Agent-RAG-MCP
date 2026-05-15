"""Agent state and result data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ToolCallRecord:
    """A single tool call made by the agent."""

    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    latency_ms: float
    result_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "result_count": self.result_count,
        }


@dataclass
class AgentState:
    """Mutable state for one agent turn."""

    query: str
    user_id: str
    session_id: str
    collection: str
    top_k: int
    memory_contexts: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    answer: str = ""


@dataclass(frozen=True)
class AgentResult:
    """Structured result returned by an agent turn."""

    answer: str
    citations: List[Dict[str, Any]]
    tool_calls: List[Dict[str, Any]]
    memory_events: List[Dict[str, Any]]
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": list(self.citations),
            "tool_calls": list(self.tool_calls),
            "memory_events": list(self.memory_events),
            "trace_id": self.trace_id,
        }
