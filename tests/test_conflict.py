"""Tests for swarm.conflict — auto-revert and agent quarantine."""

from __future__ import annotations

from pathlib import Path

from swarm.conflict import (
    ConflictState,
    check_quarantine,
    get_quarantined_agents,
    release_from_quarantine,
)


class TestConflictState:
    def test_save_and_load(self, tmp_path: Path):
        state = ConflictState()
        rec = state.get_agent("1")
        rec.failures = 2
        rec.reverted_commits = ["abc123"]
        state.save(tmp_path)

        loaded = ConflictState.load(tmp_path)
        assert loaded.agents["1"].failures == 2
        assert loaded.agents["1"].reverted_commits == ["abc123"]

    def test_load_missing_file(self, tmp_path: Path):
        state = ConflictState.load(tmp_path)
        assert state.agents == {}

    def test_load_corrupt_file(self, tmp_path: Path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "conflict-state.json").write_text("not json")
        state = ConflictState.load(tmp_path)
        assert state.agents == {}

    def test_get_agent_creates_new(self):
        state = ConflictState()
        rec = state.get_agent("5")
        assert rec.agent_id == "5"
        assert rec.failures == 0


class TestQuarantine:
    def test_quarantine_after_threshold(self):
        state = ConflictState()
        rec = state.get_agent("1")
        rec.failures = 3
        quarantined = check_quarantine(state)
        assert "1" in quarantined
        assert rec.quarantined is True

    def test_no_quarantine_below_threshold(self):
        state = ConflictState()
        rec = state.get_agent("1")
        rec.failures = 2
        quarantined = check_quarantine(state)
        assert quarantined == []

    def test_already_quarantined_not_repeated(self):
        state = ConflictState()
        rec = state.get_agent("1")
        rec.failures = 5
        rec.quarantined = True
        quarantined = check_quarantine(state)
        assert quarantined == []

    def test_get_quarantined(self):
        state = ConflictState()
        state.get_agent("1").quarantined = True
        state.get_agent("2").quarantined = False
        state.get_agent("3").quarantined = True
        assert sorted(get_quarantined_agents(state)) == ["1", "3"]


class TestRelease:
    def test_release_quarantined(self):
        state = ConflictState()
        rec = state.get_agent("1")
        rec.failures = 5
        rec.quarantined = True
        assert release_from_quarantine(state, "1") is True
        assert rec.quarantined is False
        assert rec.failures == 0

    def test_release_not_quarantined(self):
        state = ConflictState()
        state.get_agent("1")
        assert release_from_quarantine(state, "1") is False

    def test_release_unknown_agent(self):
        state = ConflictState()
        assert release_from_quarantine(state, "99") is False
