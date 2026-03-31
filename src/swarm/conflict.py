"""Advanced conflict resolution — auto-revert, CI gating, agent quarantine.

When an agent pushes code that breaks tests:
1. Auto-revert the offending commit
2. Track the agent's failure count
3. Quarantine repeat offenders (reassign to reviewer role)
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

QUARANTINE_THRESHOLD = 3  # failures before quarantine
STATE_FILE = ".swarm/conflict-state.json"


@dataclass
class AgentRecord:
    agent_id: str
    failures: int = 0
    reverted_commits: list[str] = field(default_factory=list)
    quarantined: bool = False
    last_failure_time: float = 0.0


@dataclass
class ConflictState:
    agents: dict[str, AgentRecord] = field(default_factory=dict)

    def get_agent(self, agent_id: str) -> AgentRecord:
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentRecord(agent_id=agent_id)
        return self.agents[agent_id]

    def save(self, project_dir: Path) -> None:
        path = project_dir / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            aid: {
                "agent_id": rec.agent_id,
                "failures": rec.failures,
                "reverted_commits": rec.reverted_commits,
                "quarantined": rec.quarantined,
                "last_failure_time": rec.last_failure_time,
            }
            for aid, rec in self.agents.items()
        }
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def load(project_dir: Path) -> ConflictState:
        path = project_dir / STATE_FILE
        state = ConflictState()
        if not path.is_file():
            return state
        try:
            data = json.loads(path.read_text())
            for aid, rec_data in data.items():
                state.agents[aid] = AgentRecord(**rec_data)
        except (json.JSONDecodeError, TypeError, KeyError):
            log.warning("Corrupt conflict state, starting fresh")
        return state


# ── CI Check ────────────────────────────────────────────────────────────────


def run_ci_check(repo_path: Path, test_command: str) -> bool:
    """Run tests against the repo. Returns True if tests pass."""
    try:
        cmd_parts = shlex.split(test_command)
    except ValueError:
        return True  # can't parse command, assume ok

    result = subprocess.run(
        cmd_parts,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode == 0


# ── Auto-Revert ────────────────────────────────────────────────────────────


def identify_breaking_commit(
    repo_path: Path, test_command: str, branch: str = "main", max_check: int = 5
) -> str | None:
    """Find the most recent commit that broke tests via bisection.

    Checks the last N commits, returns the hash of the first one that breaks tests.
    """
    # Get recent commit hashes
    result = subprocess.run(
        ["git", "log", "--format=%H", f"-{max_check}", branch],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    commits = result.stdout.strip().splitlines()
    if not commits:
        return None

    # Tests should be failing on HEAD (current commit)
    if run_ci_check(repo_path, test_command):
        return None  # tests pass, nothing to revert

    # Check each older commit to find where tests start passing
    for commit in commits[1:]:
        subprocess.run(
            ["git", "checkout", commit], cwd=repo_path, capture_output=True
        )
        if run_ci_check(repo_path, test_command):
            # This commit passes, so the one after it is the breaker
            subprocess.run(
                ["git", "checkout", branch], cwd=repo_path, capture_output=True
            )
            # The breaking commit is commits[commits.index(commit) - 1]
            idx = commits.index(commit)
            if idx > 0:
                return commits[idx - 1]
            return commits[0]

    # Reset back to branch head
    subprocess.run(
        ["git", "checkout", branch], cwd=repo_path, capture_output=True
    )
    return None


def get_commit_author(repo_path: Path, commit_hash: str) -> str:
    """Get the author name of a commit (e.g., 'swarm-agent-3')."""
    result = subprocess.run(
        ["git", "log", "--format=%an", "-1", commit_hash],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def revert_commit(repo_path: Path, commit_hash: str) -> bool:
    """Revert a specific commit. Returns True on success."""
    result = subprocess.run(
        ["git", "revert", "--no-edit", commit_hash],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("Failed to revert %s: %s", commit_hash, result.stderr)
        # Abort if revert had conflicts
        subprocess.run(
            ["git", "revert", "--abort"], cwd=repo_path, capture_output=True
        )
        return False

    log.info("Reverted commit %s", commit_hash)
    return True


def auto_revert_if_broken(
    repo_path: Path,
    test_command: str,
    state: ConflictState,
    branch: str = "main",
) -> str | None:
    """Check if tests are broken, find and revert the breaking commit.

    Returns the reverted commit hash, or None if nothing was reverted.
    """
    if run_ci_check(repo_path, test_command):
        return None  # tests pass

    breaking = identify_breaking_commit(repo_path, test_command, branch)
    if not breaking:
        log.warning("Tests failing but couldn't identify breaking commit")
        return None

    author = get_commit_author(repo_path, breaking)
    agent_id = author.replace("swarm-agent-", "")

    if revert_commit(repo_path, breaking):
        # Track the failure
        record = state.get_agent(agent_id)
        record.failures += 1
        record.reverted_commits.append(breaking)
        record.last_failure_time = time.time()

        log.warning(
            "Auto-reverted commit %s by agent %s (failure #%d)",
            breaking[:8], agent_id, record.failures,
        )
        return breaking

    return None


# ── Agent Quarantine ────────────────────────────────────────────────────────


def check_quarantine(
    state: ConflictState, threshold: int = QUARANTINE_THRESHOLD
) -> list[str]:
    """Check which agents should be quarantined. Returns list of agent IDs."""
    newly_quarantined = []
    for agent_id, record in state.agents.items():
        if record.failures >= threshold and not record.quarantined:
            record.quarantined = True
            newly_quarantined.append(agent_id)
            log.warning(
                "Agent %s quarantined after %d failures — reassigning to reviewer role",
                agent_id, record.failures,
            )
    return newly_quarantined


def get_quarantined_agents(state: ConflictState) -> list[str]:
    """Return list of currently quarantined agent IDs."""
    return [aid for aid, rec in state.agents.items() if rec.quarantined]


def release_from_quarantine(state: ConflictState, agent_id: str) -> bool:
    """Release an agent from quarantine. Returns True if agent was quarantined."""
    record = state.agents.get(agent_id)
    if record and record.quarantined:
        record.quarantined = False
        record.failures = 0
        record.reverted_commits.clear()
        log.info("Agent %s released from quarantine", agent_id)
        return True
    return False
