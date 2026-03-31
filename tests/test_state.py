"""Tests for swarm.state — persistence and resume."""

from __future__ import annotations

from pathlib import Path

from swarm.state import (
    SwarmState,
    can_resume,
    create_state_from_run,
    get_resume_info,
)


class TestSwarmState:
    def test_save_and_load(self, tmp_path: Path):
        state = SwarmState(project_name="test", upstream_path="/tmp/up.git")
        state.save(tmp_path)
        loaded = SwarmState.load(tmp_path)
        assert loaded is not None
        assert loaded.project_name == "test"

    def test_load_missing(self, tmp_path: Path):
        assert SwarmState.load(tmp_path) is None

    def test_load_corrupt(self, tmp_path: Path):
        (tmp_path / ".swarm").mkdir()
        (tmp_path / ".swarm" / "state.json").write_text("not json")
        assert SwarmState.load(tmp_path) is None

    def test_mark_running(self):
        state = SwarmState()
        state.mark_running()
        assert state.status == "running"
        assert state.started_at > 0

    def test_mark_stopped(self):
        state = SwarmState()
        state.mark_running()
        state.mark_stopped()
        assert state.status == "stopped"
        assert state.stopped_at > 0

    def test_clear(self, tmp_path: Path):
        state = SwarmState()
        state.save(tmp_path)
        assert (tmp_path / ".swarm" / "state.json").is_file()
        state.clear(tmp_path)
        assert not (tmp_path / ".swarm" / "state.json").is_file()


class TestCreateState:
    def test_from_run(self, tmp_path: Path):
        state = create_state_from_run(
            "proj", tmp_path, "/tmp/up.git", "main", "img:v1",
            [("1", "builder", "opus", "abc"), ("2", "tester", "sonnet", "def")],
        )
        assert state.project_name == "proj"
        assert len(state.agents) == 2
        assert state.agents[0].role == "builder"
        assert state.status == "running"


class TestCanResume:
    def test_can_resume(self, tmp_path: Path):
        state = create_state_from_run(
            "proj", tmp_path, "/tmp/up.git", "main", "img:v1",
            [("1", "builder", "opus", "abc")],
        )
        state.save(tmp_path)
        assert can_resume(tmp_path) is True

    def test_cannot_resume_empty(self, tmp_path: Path):
        assert can_resume(tmp_path) is False

    def test_cannot_resume_no_agents(self, tmp_path: Path):
        state = SwarmState(upstream_path="/tmp/up.git")
        state.save(tmp_path)
        assert can_resume(tmp_path) is False


class TestResumeInfo:
    def test_get_info(self, tmp_path: Path):
        state = create_state_from_run(
            "proj", tmp_path, "/tmp/up.git", "main", "img:v1",
            [("1", "builder", "opus", "abc")],
        )
        state.save(tmp_path)
        info = get_resume_info(tmp_path)
        assert info is not None
        assert info["project"] == "proj"
        assert info["agents"] == 1

    def test_no_state(self, tmp_path: Path):
        assert get_resume_info(tmp_path) is None
