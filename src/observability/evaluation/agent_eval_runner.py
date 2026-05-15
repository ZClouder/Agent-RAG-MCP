"""Deterministic evaluation runner for agent behavior.

The runner accepts an injected ``agent_runner(case) -> dict`` callable and
scores its output against a golden fixture. It does not call real RAG, agent,
memory, MCP, trace, or settings code.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

AGENT_EVAL_METRICS = (
    "tool_success_rate",
    "citation_presence_rate",
    "answer_contains_rate",
    "memory_write_success_rate",
    "trace_completeness_rate",
)

DEFAULT_THRESHOLDS = {metric: 1.0 for metric in AGENT_EVAL_METRICS}

AgentRunner = Callable[[dict[str, Any]], dict[str, Any]]


class AgentEvalThresholdError(AssertionError):
    """Raised when aggregate metrics do not meet configured thresholds."""


@dataclass(frozen=True)
class AgentEvalCase:
    """Validated golden case for deterministic agent evaluation."""

    case_id: str
    query: str
    expected_answer_contains: list[str]
    expected_tools: list[str]
    expected_memory_writes: int
    required_trace_fields: list[str]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int) -> AgentEvalCase:
        required_fields = (
            "id",
            "query",
            "expected_answer_contains",
            "expected_tools",
            "expected_memory_writes",
            "required_trace_fields",
        )
        missing = [field_name for field_name in required_fields if field_name not in data]
        if missing:
            raise ValueError(
                f"Agent eval case at index {index} is missing required field(s): "
                f"{', '.join(missing)}"
            )

        case_id = _require_non_empty_string(data["id"], f"test_cases[{index}].id")
        query = _require_non_empty_string(data["query"], f"test_cases[{index}].query")
        expected_answer_contains = _require_string_list(
            data["expected_answer_contains"],
            f"test_cases[{index}].expected_answer_contains",
            allow_empty=False,
        )
        expected_tools = _require_string_list(
            data["expected_tools"],
            f"test_cases[{index}].expected_tools",
            allow_empty=True,
        )
        expected_memory_writes = _require_non_negative_int(
            data["expected_memory_writes"],
            f"test_cases[{index}].expected_memory_writes",
        )
        required_trace_fields = _require_string_list(
            data["required_trace_fields"],
            f"test_cases[{index}].required_trace_fields",
            allow_empty=False,
        )

        return cls(
            case_id=case_id,
            query=query,
            expected_answer_contains=expected_answer_contains,
            expected_tools=expected_tools,
            expected_memory_writes=expected_memory_writes,
            required_trace_fields=required_trace_fields,
            raw=dict(data),
        )


@dataclass(frozen=True)
class AgentEvalCaseResult:
    """Per-case agent evaluation result."""

    case_id: str
    query: str
    metrics: dict[str, float]
    elapsed_ms: float


@dataclass(frozen=True)
class AgentEvalReport:
    """Aggregate deterministic agent evaluation report."""

    case_results: list[AgentEvalCaseResult]
    aggregate_metrics: dict[str, float]
    thresholds: dict[str, float]
    total_elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": len(self.case_results),
            "aggregate_metrics": {
                key: round(value, 4) for key, value in self.aggregate_metrics.items()
            },
            "thresholds": self.thresholds,
            "total_elapsed_ms": round(self.total_elapsed_ms, 1),
            "case_results": [
                {
                    **asdict(result),
                    "metrics": {
                        key: round(value, 4) for key, value in result.metrics.items()
                    },
                    "elapsed_ms": round(result.elapsed_ms, 1),
                }
                for result in self.case_results
            ],
        }


def load_agent_golden(path: str | Path) -> dict[str, Any]:
    """Load and validate an agent golden fixture."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Agent golden fixture not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Agent golden fixture must be a JSON object.")
    if "test_cases" not in data:
        raise ValueError("Agent golden fixture is missing required field: test_cases")
    if not isinstance(data["test_cases"], list):
        raise ValueError("Agent golden fixture field 'test_cases' must be a list.")
    if not data["test_cases"]:
        raise ValueError("Agent golden fixture contains an empty test set.")

    thresholds = data.get("thresholds", {})
    if thresholds is not None and not isinstance(thresholds, dict):
        raise ValueError("Agent golden fixture field 'thresholds' must be an object.")

    _validate_thresholds(thresholds or {})
    for index, raw_case in enumerate(data["test_cases"]):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Agent eval case at index {index} must be an object.")
        AgentEvalCase.from_dict(raw_case, index)

    return {
        "thresholds": dict(thresholds or {}),
        "test_cases": [dict(case) for case in data["test_cases"]],
    }


class AgentEvalRunner:
    """Run deterministic agent evals with an injected agent callable."""

    def __init__(
        self,
        agent_runner: AgentRunner,
        thresholds: Mapping[str, float] | None = None,
    ) -> None:
        if not callable(agent_runner):
            raise ValueError("AgentEvalRunner requires callable agent_runner.")
        self.agent_runner = agent_runner
        self.thresholds = dict(thresholds or {})
        _validate_thresholds(self.thresholds)

    def run(self, golden: str | Path | Sequence[Mapping[str, Any]]) -> AgentEvalReport:
        """Run all cases and fail fast on invalid input, agent errors, or thresholds."""

        fixture_thresholds: dict[str, float] = {}
        if isinstance(golden, (str, Path)):
            fixture = load_agent_golden(golden)
            raw_cases = fixture["test_cases"]
            fixture_thresholds = fixture["thresholds"]
        else:
            raw_cases = [dict(case) for case in golden]

        if not raw_cases:
            raise ValueError("Agent eval test set is empty.")

        thresholds = {
            **DEFAULT_THRESHOLDS,
            **fixture_thresholds,
            **self.thresholds,
        }
        _validate_thresholds(thresholds)

        started_at = time.monotonic()
        case_results: list[AgentEvalCaseResult] = []
        for index, raw_case in enumerate(raw_cases):
            case = AgentEvalCase.from_dict(raw_case, index)
            case_started_at = time.monotonic()
            try:
                agent_output = self.agent_runner(dict(case.raw))
            except Exception as exc:
                raise RuntimeError(
                    f"Agent runner failed for case '{case.case_id}': {exc}"
                ) from exc

            metrics = evaluate_agent_output(case, agent_output)
            case_results.append(
                AgentEvalCaseResult(
                    case_id=case.case_id,
                    query=case.query,
                    metrics=metrics,
                    elapsed_ms=(time.monotonic() - case_started_at) * 1000.0,
                )
            )

        aggregate_metrics = aggregate_agent_metrics(case_results)
        _assert_thresholds(aggregate_metrics, thresholds)

        return AgentEvalReport(
            case_results=case_results,
            aggregate_metrics=aggregate_metrics,
            thresholds=thresholds,
            total_elapsed_ms=(time.monotonic() - started_at) * 1000.0,
        )


def evaluate_agent_output(
    case: AgentEvalCase,
    agent_output: Mapping[str, Any],
) -> dict[str, float]:
    """Score one validated case against one validated agent output."""

    if not isinstance(agent_output, Mapping):
        raise ValueError(f"Agent output for case '{case.case_id}' must be an object.")

    missing = [
        field_name
        for field_name in ("answer", "tool_calls", "citations", "memory_writes", "trace")
        if field_name not in agent_output
    ]
    if missing:
        raise ValueError(
            f"Agent output for case '{case.case_id}' is missing required field(s): "
            f"{', '.join(missing)}"
        )

    answer = _require_non_empty_string(
        agent_output["answer"],
        f"agent_output[{case.case_id}].answer",
    )
    tool_calls = _require_list(
        agent_output["tool_calls"],
        f"agent_output[{case.case_id}].tool_calls",
    )
    citations = _require_list(
        agent_output["citations"],
        f"agent_output[{case.case_id}].citations",
    )
    memory_writes = _require_list(
        agent_output["memory_writes"],
        f"agent_output[{case.case_id}].memory_writes",
    )
    trace = agent_output["trace"]
    if not isinstance(trace, Mapping):
        raise ValueError(f"agent_output[{case.case_id}].trace must be an object.")

    return {
        "tool_success_rate": _tool_success_rate(case.expected_tools, tool_calls),
        "citation_presence_rate": 1.0 if citations else 0.0,
        "answer_contains_rate": _answer_contains_rate(
            case.expected_answer_contains,
            answer,
        ),
        "memory_write_success_rate": _memory_write_success_rate(
            case.expected_memory_writes,
            memory_writes,
        ),
        "trace_completeness_rate": _trace_completeness_rate(
            case.required_trace_fields,
            trace,
        ),
    }


def aggregate_agent_metrics(
    case_results: Iterable[AgentEvalCaseResult],
) -> dict[str, float]:
    """Average fixed agent metrics across evaluated cases."""

    results = list(case_results)
    if not results:
        raise ValueError("Cannot aggregate an empty agent eval result set.")

    return {
        metric: sum(result.metrics[metric] for result in results) / len(results)
        for metric in AGENT_EVAL_METRICS
    }


def _assert_thresholds(
    metrics: Mapping[str, float],
    thresholds: Mapping[str, float],
) -> None:
    for metric in AGENT_EVAL_METRICS:
        observed = metrics[metric]
        threshold = thresholds[metric]
        if observed < threshold:
            raise AgentEvalThresholdError(
                f"Agent eval metric '{metric}' below threshold: "
                f"observed={observed:.4f}, threshold={threshold:.4f}"
            )


def _tool_success_rate(expected_tools: Sequence[str], tool_calls: Sequence[Any]) -> float:
    if not expected_tools:
        return 1.0

    successful_tools = {
        call_name
        for call in tool_calls
        for call_name in [_extract_successful_tool_name(call)]
        if call_name
    }
    matched = sum(1 for tool in expected_tools if tool in successful_tools)
    return matched / len(expected_tools)


def _extract_successful_tool_name(tool_call: Any) -> str | None:
    if isinstance(tool_call, str):
        return tool_call
    if not isinstance(tool_call, Mapping):
        return None

    success = tool_call.get("success", True)
    if success is not True:
        return None

    for key in ("name", "tool", "tool_name"):
        value = tool_call.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _answer_contains_rate(expected_fragments: Sequence[str], answer: str) -> float:
    normalized_answer = answer.casefold()
    matched = sum(
        1
        for fragment in expected_fragments
        if fragment.casefold() in normalized_answer
    )
    return matched / len(expected_fragments)


def _memory_write_success_rate(
    expected_memory_writes: int,
    memory_writes: Sequence[Any],
) -> float:
    if expected_memory_writes == 0:
        return 1.0

    successful_writes = 0
    for write in memory_writes:
        if isinstance(write, Mapping):
            successful_writes += 1 if write.get("success", True) is True else 0
        elif write:
            successful_writes += 1

    return min(successful_writes, expected_memory_writes) / expected_memory_writes


def _trace_completeness_rate(
    required_trace_fields: Sequence[str],
    trace: Mapping[str, Any],
) -> float:
    present = sum(1 for field_name in required_trace_fields if _has_trace_value(trace, field_name))
    return present / len(required_trace_fields)


def _has_trace_value(trace: Mapping[str, Any], dotted_path: str) -> bool:
    current: Any = trace
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return current not in (None, "", [], {})


def _validate_thresholds(thresholds: Mapping[str, Any]) -> None:
    unsupported = sorted(set(thresholds) - set(AGENT_EVAL_METRICS))
    if unsupported:
        raise ValueError(f"Unsupported agent eval threshold(s): {', '.join(unsupported)}")

    for metric in AGENT_EVAL_METRICS:
        value = thresholds.get(metric, DEFAULT_THRESHOLDS[metric])
        if not isinstance(value, (int, float)):
            raise ValueError(f"Threshold for '{metric}' must be numeric.")
        if value < 0 or value > 1:
            raise ValueError(f"Threshold for '{metric}' must be between 0 and 1.")


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _require_string_list(
    value: Any,
    field_name: str,
    allow_empty: bool,
) -> list[str]:
    values = _require_list(value, field_name)
    if not allow_empty and not values:
        raise ValueError(f"{field_name} must not be empty.")
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise ValueError(f"{field_name} must contain only non-empty strings.")
    return list(values)


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return list(value)
