"""Tests for query routing integration in query_knowledge_hub."""

from __future__ import annotations

from typing import Any, List

import pytest

from src.core.query_engine.hybrid_search import HybridSearch, HybridSearchConfig
from src.core.query_engine.query_router import TaskQueryRouter
from src.core.types import RetrievalResult
from src.mcp_server.tools import query_knowledge_hub as module
from src.mcp_server.tools.query_knowledge_hub import (
    QueryKnowledgeHubConfig,
    QueryKnowledgeHubTool,
)


class CapturingTraceCollector:
    traces: List[Any] = []

    def collect(self, trace: Any) -> None:
        self.traces.append(trace)


@pytest.mark.asyncio
async def test_query_knowledge_hub_uses_rewritten_query_for_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_init(collection: str) -> None:
        captured["collection"] = collection

    def fake_search(
        query: str,
        top_k: int,
        trace: Any,
        route_decision: Any,
    ) -> list[RetrievalResult]:
        captured["search_query"] = query
        captured["route_intent"] = route_decision.intent
        return [
            RetrievalResult(
                chunk_id="chunk-1",
                score=0.9,
                text="品牌规范要求脚本避免夸大宣称。",
                metadata={"source_path": "brand-guideline.md", "title": "品牌规范"},
            )
        ]

    CapturingTraceCollector.traces = []
    monkeypatch.setattr(module, "TraceCollector", CapturingTraceCollector)

    tool = QueryKnowledgeHubTool(
        config=QueryKnowledgeHubConfig(enable_rerank=False),
    )
    monkeypatch.setattr(tool, "_ensure_initialized", fake_init)
    monkeypatch.setattr(tool, "_perform_search", fake_search)

    response = await tool.execute(
        query="这段脚本是否违反品牌规范，有哪些合规风险",
        top_k=3,
        collection="brand-docs",
    )

    assert response.is_empty is False
    assert captured["collection"] == "brand-docs"
    assert captured["route_intent"] == "script_compliance"
    assert "业务场景:script compliance" in captured["search_query"]
    assert "cite_brand_rule" in captured["search_query"]

    trace = CapturingTraceCollector.traces[0]
    routing = trace.metadata["query_routing"]
    assert routing["intent"] == "script_compliance"
    assert trace.get_stage_data("query_routing")["intent"] == "script_compliance"
    assert trace.metadata["search_query"] == captured["search_query"]


def test_query_knowledge_hub_builds_route_specific_hybrid_config() -> None:
    tool = QueryKnowledgeHubTool(config=QueryKnowledgeHubConfig(enable_rerank=False))
    tool._hybrid_search = HybridSearch(config=HybridSearchConfig(dense_top_k=20, sparse_top_k=20))
    decision = TaskQueryRouter().route("这段脚本是否违反品牌规范，有哪些合规风险")

    routed = tool._build_routed_hybrid_search(decision)

    assert routed.config.dense_top_k == decision.retrieval_profile.dense_top_k
    assert routed.config.sparse_top_k == decision.retrieval_profile.sparse_top_k
    assert routed.config.sparse_top_k > routed.config.dense_top_k
