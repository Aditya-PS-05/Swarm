"""File-based task locking — exactly as described by Carlini.

Agents claim tasks by writing lock files to `current_tasks/`.
If two agents race for the same lock, `git push` fails for the
slower one, forcing it to pick something else.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Default stale threshold: 15 minutes with no push
STALE_THRESHOLD_SECONDS = 15 * 60


def _slugify(task_name: str) -> str:
    """Convert a task name to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", task_name.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80]  # cap length


def _lock_path(lock_dir: Path, task_name: str) -> Path:
    return lock_dir / f"{_slugify(task_name)}.lock"


def acquire_lock(lock_dir: Path, task_name: str, agent_id: str) -> bool:
    """Write a lock file for a task. Returns True if the file was created (not already locked)."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = _lock_path(lock_dir, task_name)

    if lock_file.exists():
        log.debug("Lock already exists for task '%s'", task_name)
        return False

    lock_data = {
        "agent_id": agent_id,
        "task": task_name,
        "acquired_at": time.time(),
        "last_seen": time.time(),
    }
    lock_file.write_text(json.dumps(lock_data, indent=2))
    log.info("Agent %s acquired lock on '%s'", agent_id, task_name)
    return True


def release_lock(lock_dir: Path, task_name: str, agent_id: str) -> bool:
    """Delete a lock file. Returns True if removed, False if not found or wrong agent."""
    lock_file = _lock_path(lock_dir, task_name)

    if not lock_file.exists():
        return False

    try:
        lock_data = json.loads(lock_file.read_text())
        if lock_data.get("agent_id") != agent_id:
            log.warning(
                "Agent %s tried to release lock held by %s on '%s'",
                agent_id, lock_data.get("agent_id"), task_name,
            )
            return False
    except (json.JSONDecodeError, KeyError):
        pass

    lock_file.unlink()
    log.info("Agent %s released lock on '%s'", agent_id, task_name)
    return True


def is_locked(lock_dir: Path, task_name: str) -> bool:
    """Check if a task is currently locked."""
    return _lock_path(lock_dir, task_name).exists()


def get_lock_info(lock_dir: Path, task_name: str) -> dict | None:
    """Read lock file and return its data, or None if not locked."""
    lock_file = _lock_path(lock_dir, task_name)
    if not lock_file.exists():
        return None
    try:
        return json.loads(lock_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_locks(lock_dir: Path) -> list[dict]:
    """Return all active locks with agent IDs."""
    if not lock_dir.is_dir():
        return []

    locks = []
    for lock_file in lock_dir.glob("*.lock"):
        try:
            data = json.loads(lock_file.read_text())
            data["_file"] = lock_file.name
            locks.append(data)
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt lock file: %s", lock_file)
    return locks


def my_locks(lock_dir: Path, agent_id: str) -> list[dict]:
    """Return locks held by a specific agent."""
    return [lk for lk in list_locks(lock_dir) if lk.get("agent_id") == agent_id]


def detect_stale_locks(lock_dir: Path, threshold: float = STALE_THRESHOLD_SECONDS) -> list[dict]:
    """Find locks where the agent hasn't been seen in > threshold seconds."""
    now = time.time()
    stale = []
    for lock in list_locks(lock_dir):
        last_seen = lock.get("last_seen", lock.get("acquired_at", 0))
        if now - last_seen > threshold:
            stale.append(lock)
    return stale


def cleanup_stale_locks(lock_dir: Path, threshold: float = STALE_THRESHOLD_SECONDS) -> int:
    """Auto-release stale locks. Returns count of cleaned locks."""
    stale = detect_stale_locks(lock_dir, threshold)
    cleaned = 0
    for lock in stale:
        lock_file = lock_dir / lock["_file"]
        if lock_file.exists():
            lock_file.unlink()
            log.warning(
                "Cleaned stale lock: %s (agent %s, stale for %.0fs)",
                lock.get("task"),
                lock.get("agent_id"),
                time.time() - lock.get("last_seen", 0),
            )
            cleaned += 1
    return cleaned


def refresh_lock(lock_dir: Path, task_name: str, agent_id: str) -> bool:
    """Update last_seen timestamp on a lock. Returns False if lock not held by this agent."""
    lock_file = _lock_path(lock_dir, task_name)
    if not lock_file.exists():
        return False

    try:
        data = json.loads(lock_file.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    if data.get("agent_id") != agent_id:
        return False

    data["last_seen"] = time.time()
    lock_file.write_text(json.dumps(data, indent=2))
    return True
