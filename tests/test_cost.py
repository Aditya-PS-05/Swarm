"""Tests for swarm.cost — token parsing, cost calculation, limits."""

from __future__ import annotations

from pathlib import Path

from swarm.cost import (
    SessionCost,
    calculate_cost,
    check_cost_limit,
    compute_cost_summary,
    parse_token_usage,
    scan_agent_logs,
)


class TestParseTokenUsage:
    def test_total_format(self):
        inp, out = parse_token_usage("Total tokens: 12,345 input, 6,789 output")
        assert inp == 12345
        assert out == 6789

    def test_input_output_format(self):
        inp, out = parse_token_usage("Input tokens: 1000 | Output tokens: 500")
        assert inp == 1000
        assert out == 500

    def test_json_format(self):
        inp, out = parse_token_usage('{"input": 2000, "output": 800}')
        assert inp == 2000
        assert out == 800

    def test_no_match(self):
        inp, out = parse_token_usage("no token info here")
        assert inp == 0
        assert out == 0


class TestCalculateCost:
    def test_opus_pricing(self):
        # 1M input tokens at $15/M = $15, 1M output tokens at $75/M = $75
        cost = calculate_cost(1_000_000, 1_000_000, "claude-opus-4-6")
        assert cost == 90.0

    def test_sonnet_pricing(self):
        cost = calculate_cost(1_000_000, 1_000_000, "claude-sonnet-4-6")
        assert cost == 18.0

    def test_unknown_model_defaults_to_opus(self):
        cost = calculate_cost(1_000_000, 0, "unknown-model")
        assert cost == 15.0


class TestComputeSummary:
    def test_aggregation(self):
        sessions = [
            SessionCost("1", 100000, 50000, 5.0),
            SessionCost("1", 200000, 80000, 8.0),
            SessionCost("2", 150000, 60000, 6.0),
        ]
        summary = compute_cost_summary(sessions)
        assert summary.total_cost_usd == 19.0
        assert summary.total_input_tokens == 450000
        assert summary.total_output_tokens == 190000
        assert summary.cost_by_agent["1"] == 13.0
        assert summary.cost_by_agent["2"] == 6.0

    def test_empty_sessions(self):
        summary = compute_cost_summary([])
        assert summary.total_cost_usd == 0.0


class TestCheckCostLimit:
    def test_under_limit(self):
        summary = compute_cost_summary([SessionCost("1", 0, 0, 10.0)])
        assert check_cost_limit(summary, 100.0) is False

    def test_over_limit(self):
        summary = compute_cost_summary([SessionCost("1", 0, 0, 60.0)])
        assert check_cost_limit(summary, 50.0) is True

    def test_at_limit(self):
        summary = compute_cost_summary([SessionCost("1", 0, 0, 50.0)])
        assert check_cost_limit(summary, 50.0) is True


class TestScanAgentLogs:
    def test_scan_logs(self, tmp_path: Path):
        logs_dir = tmp_path / "agent_logs"
        logs_dir.mkdir()
        (logs_dir / "1_session_1_123.log").write_text(
            "Some output\nTotal tokens: 10,000 input, 5,000 output\nDone\n"
        )
        sessions = scan_agent_logs(logs_dir)
        assert len(sessions) == 1
        assert sessions[0].input_tokens == 10000
        assert sessions[0].output_tokens == 5000

    def test_empty_dir(self, tmp_path: Path):
        assert scan_agent_logs(tmp_path / "nope") == []
