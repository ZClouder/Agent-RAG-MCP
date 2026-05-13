"""Tests for TraceService (G5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.observability.dashboard.services.trace_service import TraceService


@pytest.fixture()
def traces_file(tmp_path: Path) -> Path:
    p = tmp_path / "traces.jsonl"
    traces = [
        {
            "trace_id": "t1",
            "trace_type": "ingestion",
            "started_at": "2025-01-01T00:00:00",
            "elapsed_ms": 100.0,
            "stages": [
                {"stage": "load", "elapsed_ms": 20.0, "data": {"method": "pdf"}},
                {"stage": "split", "elapsed_ms": 30.0},
                {"stage": "embed", "elapsed_ms": 50.0},
            ],
            "metadata": {"source": "a.pdf"},
        },
        {
            "trace_id": "t2",
            "trace_type": "query",
            "started_at": "2025-01-02T00:00:00",
            "elapsed_ms": 50.0,
            "stages": [
                {"stage": "dense_retrieval", "elapsed_ms": 25.0},
                {"stage": "rerank", "elapsed_ms": 25.0},
            ],
            "metadata": {},
        },
        {
            "trace_id": "t3",
            "trace_type": "ingestion",
            "started_at": "2025-01-03T00:00:00",
            "elapsed_ms": 200.0,
            "stages": [],
            "metadata": {},
        },
        {
            "trace_id": "t4",
            "trace_type": "agent",
            "started_at": "2025-01-04T00:00:00",
            "elapsed_ms": 75.0,
            "stages": [
                {
                    "stage": "agent_start",
                    "elapsed_ms": 5.0,
                    "data": {"success": True, "output_count": 1},
                },
                {
                    "stage": "tool_call",
                    "elapsed_ms": 50.0,
                    "data": {"success": True, "tool_name": "query_knowledge_hub"},
                },
            ],
            "metadata": {"session_id": "s1"},
        },
    ]
    with p.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    return p


class TestTraceService:

    def test_list_all(self, traces_file):
        svc = TraceService(traces_file)
        result = svc.list_traces()
        assert len(result) == 4
        # Newest first
        assert result[0]["trace_id"] == "t4"

    def test_list_by_type(self, traces_file):
        svc = TraceService(traces_file)
        ing = svc.list_traces(trace_type="ingestion")
        assert len(ing) == 2
        assert all(t["trace_type"] == "ingestion" for t in ing)

    def test_list_by_type_query(self, traces_file):
        svc = TraceService(traces_file)
        q = svc.list_traces(trace_type="query")
        assert len(q) == 1
        assert q[0]["trace_id"] == "t2"

    def test_list_by_type_agent(self, traces_file):
        svc = TraceService(traces_file)
        agent = svc.list_traces(trace_type="agent")
        assert len(agent) == 1
        assert agent[0]["trace_id"] == "t4"
        assert agent[0]["metadata"]["session_id"] == "s1"

    def test_get_stage_timings_for_agent_trace(self, traces_file):
        svc = TraceService(traces_file)
        t = svc.get_trace("t4")
        timings = svc.get_stage_timings(t)
        assert [item["stage_name"] for item in timings] == ["agent_start", "tool_call"]
        assert timings[1]["data"]["tool_name"] == "query_knowledge_hub"

    def test_list_with_limit(self, traces_file):
        svc = TraceService(traces_file)
        result = svc.list_traces(limit=1)
        assert len(result) == 1

    def test_get_trace_found(self, traces_file):
        svc = TraceService(traces_file)
        t = svc.get_trace("t1")
        assert t is not None
        assert t["trace_id"] == "t1"

    def test_get_trace_not_found(self, traces_file):
        svc = TraceService(traces_file)
        assert svc.get_trace("no_such") is None

    def test_get_stage_timings(self, traces_file):
        svc = TraceService(traces_file)
        t = svc.get_trace("t1")
        timings = svc.get_stage_timings(t)
        assert len(timings) == 3
        assert timings[0]["stage_name"] == "load"
        assert timings[0]["elapsed_ms"] == 20.0
        assert timings[0]["data"]["method"] == "pdf"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.touch()
        svc = TraceService(p)
        assert svc.list_traces() == []

    def test_missing_file(self, tmp_path):
        svc = TraceService(tmp_path / "nonexistent.jsonl")
        assert svc.list_traces() == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"trace_id": "ok", "trace_type": "query", "started_at": ""}\nNOT_JSON\n')
        svc = TraceService(p)
        result = svc.list_traces()
        assert len(result) == 1
        assert result[0]["trace_id"] == "ok"
