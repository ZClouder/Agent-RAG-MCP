"""MCP Tool: agent_answer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from mcp import types

from src.agent import AgentOrchestrator
from src.core.settings import resolve_path
from src.memory import MemoryManager
from src.mcp_server.tools.query_knowledge_hub import query_knowledge_hub_handler

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_answer"
TOOL_DESCRIPTION = """Answer a user query through the Agent-RAG-Memory loop.

The tool retrieves scoped episodic memory, calls query_knowledge_hub, composes
a citation-backed answer, writes memory for successful turns, and records an
agent trace.
"""

TOOL_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "User query."},
        "user_id": {"type": "string", "description": "Required user scope."},
        "session_id": {"type": "string", "description": "Required session scope."},
        "collection": {"type": "string", "description": "Required RAG collection."},
        "top_k": {
            "type": "integer",
            "description": "Number of RAG results to retrieve.",
            "minimum": 1,
            "maximum": 20,
        },
    },
    "required": ["query", "user_id", "session_id", "collection", "top_k"],
}

_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Return the process-wide Agent orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        memory_db = resolve_path(Path("data") / "db" / "episodic_memory.db")
        _orchestrator = AgentOrchestrator(
            query_tool_handler=query_knowledge_hub_handler,
            memory_manager=MemoryManager(db_path=str(memory_db)),
        )
    return _orchestrator


def set_orchestrator_for_testing(orchestrator: Optional[AgentOrchestrator]) -> None:
    """Inject an orchestrator for tests."""
    global _orchestrator
    _orchestrator = orchestrator


async def agent_answer_handler(
    query: str,
    user_id: str,
    session_id: str,
    collection: str,
    top_k: int,
) -> types.CallToolResult:
    """Handle MCP calls to the agent_answer tool."""
    try:
        result = await get_orchestrator().answer(
            query=query,
            user_id=user_id,
            session_id=session_id,
            collection=collection,
            top_k=top_k,
        )
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                )
            ],
            isError=False,
        )
    except Exception as exc:
        logger.exception("agent_answer failed")
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"agent_answer failed: {exc}",
                )
            ],
            isError=True,
        )


def register_tool(protocol_handler) -> None:
    """Register agent_answer with the protocol handler."""
    protocol_handler.register_tool(
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        input_schema=TOOL_INPUT_SCHEMA,
        handler=agent_answer_handler,
    )
    logger.info("Registered MCP tool: %s", TOOL_NAME)
