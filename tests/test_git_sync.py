"""Tests for swarm.git_sync — bare repo, clone, push/pull."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from swarm.git_sync import (
    GitSyncError,
    clone_for_agent,
    create_bare_repo,
    push_to_upstream,
    run_test_gate,
    sync_pull,
    sync_push,
    sync_status,
    verify_upstream,
)


def _init_project(path: Path, branch: str = "main") -> Path:
    """Create a minimal git repo to act as a project."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


class TestBareRepo:
    def test_create_bare_repo(self, tmp_path: Path):
        bare = tmp_path / "upstream.git"
        create_bare_repo(bare)
        assert (bare / "HEAD").exists()

    def test_push_and_verify(self, tmp_path: Path):
        project = _init_project(tmp_path / "project")
        bare = tmp_path / "upstream.git"
        create_bare_repo(bare)
        push_to_upstream(project, bare)
        assert verify_upstream(bare) is True

    def test_verify_empty_repo(self, tmp_path: Path):
        bare = tmp_path / "upstream.git"
        create_bare_repo(bare)
        assert verify_upstream(bare) is False


class TestClone:
    def test_clone_for_agent(self, tmp_path: Path):
        project = _init_project(tmp_path / "project")
        bare = tmp_path / "upstream.git"
        create_bare_repo(bare)
        push_to_upstream(project, bare)

        workspace = tmp_path / "agent-1"
        clone_for_agent(bare, workspace, "1")
        assert (workspace / "README.md").exists()
        assert (workspace / ".git").is_dir()


class TestSyncProtocol:
    def _setup(self, tmp_path: Path):
        """Set up project, bare repo, and two agent workspaces."""
        project = _init_project(tmp_path / "project")
        bare = tmp_path / "upstream.git"
        create_bare_repo(bare)
        push_to_upstream(project, bare)

        ws1 = tmp_path / "agent-1"
        ws2 = tmp_path / "agent-2"
        clone_for_agent(bare, ws1, "1")
        clone_for_agent(bare, ws2, "2")
        return bare, ws1, ws2

    def test_push_and_pull(self, tmp_path: Path):
        bare, ws1, ws2 = self._setup(tmp_path)

        # Agent 1 makes a change and pushes
        (ws1 / "file1.txt").write_text("hello from agent 1\n")
        subprocess.run(["git", "add", "."], cwd=ws1, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "agent 1 work"], cwd=ws1, check=True, capture_output=True)
        assert sync_push(ws1) is True

        # Agent 2 pulls and sees the change
        assert sync_pull(ws2) is True
        assert (ws2 / "file1.txt").read_text() == "hello from agent 1\n"

    def test_sync_status(self, tmp_path: Path):
        bare, ws1, ws2 = self._setup(tmp_path)

        (ws1 / "file1.txt").write_text("new\n")
        subprocess.run(["git", "add", "."], cwd=ws1, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "ahead"], cwd=ws1, check=True, capture_output=True)

        status = sync_status(ws1)
        assert status["ahead"] == 1
        assert status["behind"] == 0


class TestTestGate:
    def test_passing_gate(self, tmp_path: Path):
        assert run_test_gate(tmp_path, "true") is True

    def test_failing_gate(self, tmp_path: Path):
        assert run_test_gate(tmp_path, "false") is False
