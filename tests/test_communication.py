"""Tests for swarm.communication — agent file-based communication."""

from __future__ import annotations

from pathlib import Path

from swarm.communication import (
    generate_communication_prompt_section,
    get_agent_progress,
    get_decisions,
    get_failed_approaches,
    is_known_failure,
    log_decision,
    log_failed_approach,
    log_progress,
)


class TestProgress:
    def test_log_and_read(self, tmp_path: Path):
        log_progress(tmp_path, "1", 1, ["Did X", "Did Y"])
        entries = get_agent_progress(tmp_path, "1")
        assert len(entries) > 0
        assert "Did X" in "\n".join(entries)

    def test_multiple_agents(self, tmp_path: Path):
        log_progress(tmp_path, "1", 1, ["Task A"])
        log_progress(tmp_path, "2", 1, ["Task B"])
        agent1 = get_agent_progress(tmp_path, "1")
        agent2 = get_agent_progress(tmp_path, "2")
        assert "Task A" in "\n".join(agent1)
        assert "Task B" in "\n".join(agent2)

    def test_creates_file(self, tmp_path: Path):
        log_progress(tmp_path, "1", 1, ["First"])
        assert (tmp_path / "PROGRESS.md").is_file()


class TestFailedApproaches:
    def test_log_and_read(self, tmp_path: Path):
        log_failed_approach(tmp_path, "1", "Auth", "JWT", "Library broken")
        failures = get_failed_approaches(tmp_path)
        assert len(failures) == 1
        assert failures[0]["task"] == "Auth"
        assert failures[0]["approach"] == "JWT"

    def test_known_failure_check(self, tmp_path: Path):
        log_failed_approach(tmp_path, "1", "DB setup", "SQLite", "Concurrency issues")
        assert is_known_failure(tmp_path, "DB setup", "SQLite") is True
        assert is_known_failure(tmp_path, "DB setup", "PostgreSQL") is False

    def test_empty_file(self, tmp_path: Path):
        assert get_failed_approaches(tmp_path) == []


class TestDecisions:
    def test_log_and_read(self, tmp_path: Path):
        log_decision(tmp_path, "1", "Use REST", "Need API", "REST over GraphQL", ["GraphQL"])
        decisions = get_decisions(tmp_path)
        assert len(decisions) == 1
        assert decisions[0]["title"] == "Use REST"
        assert decisions[0]["decision"] == "REST over GraphQL"

    def test_multiple_decisions(self, tmp_path: Path):
        log_decision(tmp_path, "1", "Decision A", "ctx", "chose A")
        log_decision(tmp_path, "2", "Decision B", "ctx", "chose B")
        decisions = get_decisions(tmp_path)
        assert len(decisions) == 2


class TestPromptSection:
    def test_generates_section(self, tmp_path: Path):
        log_progress(tmp_path, "1", 1, ["Did stuff"])
        log_failed_approach(tmp_path, "1", "X", "Y", "Z")
        log_decision(tmp_path, "1", "D", "ctx", "chose D")
        section = generate_communication_prompt_section(tmp_path)
        assert "Recent Progress" in section
        assert "Known Failed Approaches" in section
        assert "Architectural Decisions" in section

    def test_empty_workspace(self, tmp_path: Path):
        section = generate_communication_prompt_section(tmp_path)
        assert "Shared Knowledge" in section
