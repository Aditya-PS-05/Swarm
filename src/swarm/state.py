"""Swarm state persistence — save/restore session state for resume & recovery.

State is persisted to .swarm/state.json and includes:
- Which agents were running and their roles
- Config snapshot (model, branch, upstream path)
- Session counts per agent
- Timestamp of last run
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATE_FILE = ".swarm/state.json"


@dataclass
class AgentState:
    agent_id: str
    role: str
    model: str
    container_id: str = ""
    session_count: int = 0
    status: str = "running"  # running, stopped, crashed


@dataclass
class SwarmState:
    project_name: str = ""
    project_dir: str = ""
    upstream_path: str = ""
    branch: str = "main"
    image_tag: str = ""
    agents: list[AgentState] = field(default_factory=list)
    started_at: float = 0.0
    stopped_at: float = 0.0
    total_sessions: int = 0
    status: str = "stopped"  # running, stopped

    def save(self, project_dir: Path) -> None:
        """Persist state to .swarm/state.json."""
        path = project_dir / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2))
        log.debug("Saved swarm state to %s", path)

    @staticmethod
    def load(project_dir: Path) -> SwarmState | None:
        """Load state from .swarm/state.json. Returns None if not found."""
        path = project_dir / STATE_FILE
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
            agents = [AgentState(**a) for a in data.pop("agents", [])]
            state = SwarmState(**data)
            state.agents = agents
            return state
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log.warning("Corrupt state file: %s", e)
            return None

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = time.time()
        self.stopped_at = 0.0

    def mark_stopped(self) -> None:
        self.status = "stopped"
        self.stopped_at = time.time()

    def clear(self, project_dir: Path) -> None:
        """Delete the state file."""
        path = project_dir / STATE_FILE
        if path.is_file():
            path.unlink()
            log.debug("Cleared swarm state")


def create_state_from_run(
    project_name: str,
    project_dir: Path,
    upstream_path: str,
    branch: str,
    image_tag: str,
    agents: list[tuple[str, str, str, str]],  # (agent_id, role, model, container_id)
) -> SwarmState:
    """Create a SwarmState from a fresh run."""
    state = SwarmState(
        project_name=project_name,
        project_dir=str(project_dir),
        upstream_path=upstream_path,
        branch=branch,
        image_tag=image_tag,
        agents=[
            AgentState(
                agent_id=aid,
                role=role,
                model=model,
                container_id=cid,
                status="running",
            )
            for aid, role, model, cid in agents
        ],
    )
    state.mark_running()
    return state


def can_resume(project_dir: Path) -> bool:
    """Check if there's a valid state to resume from."""
    state = SwarmState.load(project_dir)
    if state is None:
        return False
    # Must have been running and have agents
    return len(state.agents) > 0 and state.upstream_path != ""


def get_resume_info(project_dir: Path) -> dict | None:
    """Get a summary of what would be resumed."""
    state = SwarmState.load(project_dir)
    if state is None:
        return None
    return {
        "project": state.project_name,
        "agents": len(state.agents),
        "upstream": state.upstream_path,
        "branch": state.branch,
        "image": state.image_tag,
        "status": state.status,
        "started_at": state.started_at,
        "stopped_at": state.stopped_at,
        "roles": {a.agent_id: a.role for a in state.agents},
    }
