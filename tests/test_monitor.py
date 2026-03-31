"""Tests for swarm.monitor — status collection, health checks."""

from __future__ import annotations

from swarm.monitor import AgentStatus, SwarmStatus, get_health_warnings


class TestHealthWarnings:
    def test_stuck_warning(self):
        status = SwarmStatus(agents=[AgentStatus("1", status="stuck")])
        warnings = get_health_warnings(status)
        assert len(warnings) == 1
        assert "stuck" in warnings[0]

    def test_crash_looping_warning(self):
        status = SwarmStatus(
            agents=[AgentStatus("2", status="crash-looping", session_count=5, total_commits=5)]
        )
        warnings = get_health_warnings(status)
        assert len(warnings) == 1
        assert "crash-looping" in warnings[0]

    def test_no_commits_warning(self):
        status = SwarmStatus(agents=[AgentStatus("3", status="no-commits")])
        warnings = get_health_warnings(status)
        assert "no commits" in warnings[0]

    def test_healthy_no_warnings(self):
        status = SwarmStatus(agents=[AgentStatus("1", status="healthy")])
        warnings = get_health_warnings(status)
        assert warnings == []

    def test_multiple_agents(self):
        status = SwarmStatus(
            agents=[
                AgentStatus("1", status="healthy"),
                AgentStatus("2", status="stuck"),
                AgentStatus("3", status="healthy"),
            ]
        )
        warnings = get_health_warnings(status)
        assert len(warnings) == 1
