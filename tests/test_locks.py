"""Tests for swarm.locks — file-based task locking."""

from __future__ import annotations

import json
import time
from pathlib import Path

from swarm.locks import (
    acquire_lock,
    cleanup_stale_locks,
    detect_stale_locks,
    is_locked,
    list_locks,
    my_locks,
    refresh_lock,
    release_lock,
)


class TestAcquireRelease:
    def test_acquire_creates_lock(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        assert acquire_lock(lock_dir, "task-one", "agent-1") is True
        assert is_locked(lock_dir, "task-one") is True

    def test_cannot_acquire_twice(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-one", "agent-1")
        assert acquire_lock(lock_dir, "task-one", "agent-2") is False

    def test_release_removes_lock(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-one", "agent-1")
        assert release_lock(lock_dir, "task-one", "agent-1") is True
        assert is_locked(lock_dir, "task-one") is False

    def test_release_wrong_agent_fails(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-one", "agent-1")
        assert release_lock(lock_dir, "task-one", "agent-2") is False
        assert is_locked(lock_dir, "task-one") is True

    def test_release_nonexistent_returns_false(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        assert release_lock(lock_dir, "no-task", "agent-1") is False


class TestListLocks:
    def test_list_all(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-a", "agent-1")
        acquire_lock(lock_dir, "task-b", "agent-2")
        locks = list_locks(lock_dir)
        assert len(locks) == 2

    def test_my_locks(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-a", "agent-1")
        acquire_lock(lock_dir, "task-b", "agent-2")
        acquire_lock(lock_dir, "task-c", "agent-1")
        mine = my_locks(lock_dir, "agent-1")
        assert len(mine) == 2

    def test_empty_dir(self, tmp_path: Path):
        assert list_locks(tmp_path / "nope") == []


class TestStaleLocks:
    def test_detect_stale(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "old-task", "agent-1")
        # Manually backdate the lock
        lock_file = list(lock_dir.glob("*.lock"))[0]
        data = json.loads(lock_file.read_text())
        data["last_seen"] = time.time() - 3600  # 1 hour ago
        lock_file.write_text(json.dumps(data))

        stale = detect_stale_locks(lock_dir, threshold=60)
        assert len(stale) == 1

    def test_cleanup_stale(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "old-task", "agent-1")
        lock_file = list(lock_dir.glob("*.lock"))[0]
        data = json.loads(lock_file.read_text())
        data["last_seen"] = time.time() - 3600
        lock_file.write_text(json.dumps(data))

        cleaned = cleanup_stale_locks(lock_dir, threshold=60)
        assert cleaned == 1
        assert list_locks(lock_dir) == []


class TestRefreshLock:
    def test_refresh_updates_timestamp(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-a", "agent-1")
        assert refresh_lock(lock_dir, "task-a", "agent-1") is True

    def test_refresh_wrong_agent(self, tmp_path: Path):
        lock_dir = tmp_path / "locks"
        acquire_lock(lock_dir, "task-a", "agent-1")
        assert refresh_lock(lock_dir, "task-a", "agent-2") is False
