"""Unit tests for task-oriented content-operations query routing."""

from __future__ import annotations

import pytest

from src.core.query_engine.query_router import TaskQueryRouter


@pytest.fixture()
def router() -> TaskQueryRouter:
    return TaskQueryRouter()


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("帮我核查这款产品的功效卖点是否准确", "product_verification"),
        ("生成一份小红书新品投放 brief", "brief_generation"),
        ("下周新品内容选题有哪些方向", "topic_ideation"),
        ("这段脚本是否违反品牌规范，有哪些合规风险", "script_compliance"),
        ("复盘上次活动转化差的原因并给优化建议", "review_optimization"),
    ],
)
def test_router_classifies_business_intents(
    router: TaskQueryRouter,
    query: str,
    intent: str,
) -> None:
    decision = router.route(query)

    assert decision.intent == intent
    assert decision.confidence > 0
    assert decision.preferred_doc_types
    assert decision.evidence_requirements


def test_router_falls_back_to_general_for_low_signal_query(
    router: TaskQueryRouter,
) -> None:
    decision = router.route("你好")

    assert decision.intent == "general"
    assert decision.rewritten_query == "你好"
    assert decision.confidence == 0.0


def test_router_rewrites_with_business_graph_context(router: TaskQueryRouter) -> None:
    decision = router.route("这段脚本是否合规")

    assert decision.intent == "script_compliance"
    assert "业务场景:script compliance" in decision.rewritten_query
    assert "brand_guideline" in decision.rewritten_query
    assert "cite_brand_rule" in decision.rewritten_query
    assert decision.retrieval_profile.sparse_top_k > decision.retrieval_profile.dense_top_k


def test_router_does_not_invent_product_facts(router: TaskQueryRouter) -> None:
    decision = router.route("核查产品A的卖点")

    assert "产品A" in decision.rewritten_query
    assert "第一" not in decision.rewritten_query
    assert "最好" not in decision.rewritten_query
