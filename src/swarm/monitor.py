"""Agent monitor — track what agents are doing without interfering.

Collects status from git log, lock files, and agent logs.
Detects stuck, crash-looping, and conflict-stuck agents.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class AgentStatus:
    agent_id: str
    role: str = ""
    current_task: str = ""
    last_commit_msg: str = ""
    last_commit_time: str = ""
    session_count: int = 0
    total_commits: int = 0
    status: str = "unknown"  # running, stuck, crash-looping, healthy


@dataclass
class SwarmStatus:
    agents: list[AgentStatus] = field(default_factory=list)
    total_commits: int = 0
    active_locks: int = 0
    timestamp: float = field(default_factory=time.time)


def get_agent_commits(upstream_path: Path, agent_id: str, branch: str = "main") -> list[dict]:
    """Get recent commits by a specific agent from the upstream repo."""
    author = f"swarm-agent-{agent_id}"
    result = subprocess.run(
        [
            "git", "log", "--author", author,
            "--format=%H|%s|%ai",
            "-20", branch,
        ],
        cwd=upstream_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0],
                "message": parts[1],
                "time": parts[2],
            })
    return commits


def count_agent_sessions(upstream_path: Path, agent_id: str, branch: str = "main") -> int:
    """Count sessions by looking for session commit messages."""
    commits = get_agent_commits(upstream_path, agent_id, branch)
    return sum(1 for c in commits if "session" in c["message"].lower())


def get_active_locks(lock_dir: Path) -> list[dict]:
    """Read current lock files."""
    import json

    if not lock_dir.is_dir():
        return []

    locks = []
    for lock_file in lock_dir.glob("*.lock"):
        try:
            data = json.loads(lock_file.read_text())
            locks.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return locks


def collect_agent_status(
    upstream_path: Path,
    lock_dir: Path,
    agent_id: str,
    role: str = "",
    branch: str = "main",
) -> AgentStatus:
    """Collect full status for a single agent."""
    commits = get_agent_commits(upstream_path, agent_id, branch)
    locks = get_active_locks(lock_dir)
    agent_locks = [lk for lk in locks if lk.get("agent_id") == agent_id]

    status = AgentStatus(
        agent_id=agent_id,
        role=role,
        total_commits=len(commits),
        session_count=count_agent_sessions(upstream_path, agent_id, branch),
    )

    if commits:
        status.last_commit_msg = commits[0]["message"]
        status.last_commit_time = commits[0]["time"]

    if agent_locks:
        status.current_task = agent_locks[0].get("task", "unknown")

    status.status = _evaluate_health(status, commits)
    return status


def _evaluate_health(agent: AgentStatus, commits: list[dict]) -> str:
    """Determine agent health status."""
    if not commits:
        return "no-commits"

    # Check if agent is stuck (no commits in last 15 minutes)
    try:
        from datetime import datetime, timezone

        last_time_str = commits[0]["time"].strip()
        # Git date format: 2026-03-31 16:55:00 +0000
        last_time = datetime.strptime(last_time_str[:19], "%Y-%m-%d %H:%M:%S")
        last_time = last_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        minutes_since = (now - last_time).total_seconds() / 60

        if minutes_since > 15:
            return "stuck"
    except (ValueError, IndexError):
        pass

    # Check for crash-looping (multiple sessions, very few real commits)
    if agent.session_count > 3 and agent.total_commits <= agent.session_count:
        return "crash-looping"

    return "healthy"


def collect_swarm_status(
    upstream_path: Path,
    lock_dir: Path,
    agent_ids: list[str],
    roles: dict[str, str] | None = None,
    branch: str = "main",
) -> SwarmStatus:
    """Collect status for all agents."""
    roles = roles or {}
    agents = [
        collect_agent_status(upstream_path, lock_dir, aid, roles.get(aid, ""), branch)
        for aid in agent_ids
    ]
    locks = get_active_locks(lock_dir)

    total_commits = sum(a.total_commits for a in agents)

    return SwarmStatus(
        agents=agents,
        total_commits=total_commits,
        active_locks=len(locks),
    )


def get_health_warnings(status: SwarmStatus) -> list[str]:
    """Generate health warnings from swarm status."""
    warnings = []
    for agent in status.agents:
        if agent.status == "stuck":
            warnings.append(
                f"Agent {agent.agent_id} appears stuck — no commits in >15 minutes"
            )
        elif agent.status == "crash-looping":
            warnings.append(
                f"Agent {agent.agent_id} may be crash-looping — "
                f"{agent.session_count} sessions but only {agent.total_commits} commits"
            )
        elif agent.status == "no-commits":
            warnings.append(
                f"Agent {agent.agent_id} has no commits yet"
            )
    return warnings
