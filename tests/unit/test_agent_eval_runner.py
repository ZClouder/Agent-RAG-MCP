"""Unit tests for deterministic agent eval runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.observability.evaluation.agent_eval_runner import (
    AGENT_EVAL_METRICS,
    AgentEvalRunner,
    AgentEvalThresholdError,
    aggregate_agent_metrics,
    load_agent_golden,
)


def _case(case_id: str = "case-1") -> dict[str, Any]:
    return {
        "id": case_id,
        "query": "How should an agent cite retrieved information?",
        "expected_answer_contains": ["cite", "retrieved"],
        "expected_tools": ["query_knowledge_hub"],
        "expected_memory_writes": 1,
        "required_trace_fields": ["planning", "tool_execution", "answering"],
    }


def _passing_output(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": "The agent should cite retrieved information.",
        "tool_calls": [{"name": "query_knowledge_hub", "success": True}],
        "citations": [{"source": "agent-guide.md"}],
        "memory_writes": [{"key": "agent-citation-rule", "success": True}],
        "trace": {
            "planning": {"step": "done"},
            "tool_execution": {"step": "done"},
            "answering": {"step": "done"},
        },
    }


class TestAgentEvalRunner:
    def test_run_aggregates_fixed_metrics(self) -> None:
        cases = [_case("case-1"), _case("case-2")]

        report = AgentEvalRunner(_passing_output).run(cases)

        assert len(report.case_results) == 2
        assert set(report.aggregate_metrics) == set(AGENT_EVAL_METRICS)
        assert report.aggregate_metrics == {
            "tool_success_rate": 1.0,
            "citation_presence_rate": 1.0,
            "answer_contains_rate": 1.0,
            "memory_write_success_rate": 1.0,
            "trace_completeness_rate": 1.0,
        }
        assert report.to_dict()["case_count"] == 2

    def test_threshold_failure_raises(self) -> None:
        def runner(_: dict[str, Any]) -> dict[str, Any]:
            output = _passing_output({})
            output["citations"] = []
            return output

        eval_runner = AgentEvalRunner(
            runner,
            thresholds={"citation_presence_rate": 1.0},
        )

        with pytest.raises(AgentEvalThresholdError, match="citation_presence_rate"):
            eval_runner.run([_case()])

    def test_missing_case_field_raises(self) -> None:
        bad_case = _case()
        del bad_case["expected_tools"]

        with pytest.raises(ValueError, match="expected_tools"):
            AgentEvalRunner(_passing_output).run([bad_case])

    def test_missing_agent_output_field_raises(self) -> None:
        def runner(_: dict[str, Any]) -> dict[str, Any]:
            output = _passing_output({})
            del output["trace"]
            return output

        with pytest.raises(ValueError, match="trace"):
            AgentEvalRunner(runner).run([_case()])

    def test_agent_exception_raises_runtime_error(self) -> None:
        def runner(_: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("boom")

        with pytest.raises(RuntimeError, match="case-1"):
            AgentEvalRunner(runner).run([_case()])

    def test_empty_test_set_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            AgentEvalRunner(_passing_output).run([])


class TestAgentEvalGoldenFixture:
    def test_golden_fixture_loads(self) -> None:
        fixture = load_agent_golden(Path("tests/fixtures/eval/agent_golden.json"))

        assert len(fixture["test_cases"]) >= 1
        assert set(fixture["thresholds"]) <= set(AGENT_EVAL_METRICS)

    def test_runner_loads_fixture_path(self, tmp_path: Path) -> None:
        fixture_path = tmp_path / "agent_golden.json"
        fixture_path.write_text(
            json.dumps(
                {
                    "thresholds": {
                        "tool_success_rate": 1.0,
                        "citation_presence_rate": 1.0,
                        "answer_contains_rate": 1.0,
                        "memory_write_success_rate": 1.0,
                        "trace_completeness_rate": 1.0,
                    },
                    "test_cases": [_case()],
                }
            ),
            encoding="utf-8",
        )

        report = AgentEvalRunner(_passing_output).run(fixture_path)

        assert report.aggregate_metrics["tool_success_rate"] == 1.0


class TestAgentEvalAggregation:
    def test_aggregate_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            aggregate_agent_metrics([])
