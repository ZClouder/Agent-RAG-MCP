"""
MCP Server Tools.

This package contains the MCP tool definitions exposed to clients.
"""

from src.mcp_server.tools.query_knowledge_hub import (
    TOOL_NAME as QUERY_KNOWLEDGE_HUB_NAME,
    TOOL_DESCRIPTION as QUERY_KNOWLEDGE_HUB_DESCRIPTION,
    TOOL_INPUT_SCHEMA as QUERY_KNOWLEDGE_HUB_SCHEMA,
    QueryKnowledgeHubTool,
    query_knowledge_hub_handler,
    register_tool as register_query_knowledge_hub,
)
from src.mcp_server.tools.agent_answer import (
    TOOL_NAME as AGENT_ANSWER_NAME,
    TOOL_DESCRIPTION as AGENT_ANSWER_DESCRIPTION,
    TOOL_INPUT_SCHEMA as AGENT_ANSWER_SCHEMA,
    agent_answer_handler,
    register_tool as register_agent_answer,
)

__all__ = [
    "AGENT_ANSWER_NAME",
    "AGENT_ANSWER_DESCRIPTION",
    "AGENT_ANSWER_SCHEMA",
    "QUERY_KNOWLEDGE_HUB_NAME",
    "QUERY_KNOWLEDGE_HUB_DESCRIPTION",
    "QUERY_KNOWLEDGE_HUB_SCHEMA",
    "QueryKnowledgeHubTool",
    "agent_answer_handler",
    "query_knowledge_hub_handler",
    "register_agent_answer",
    "register_query_knowledge_hub",
]
