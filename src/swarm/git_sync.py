"""Git sync engine — bare repo, clone, push/pull with conflict resolution.

Follows Carlini's pattern: bare upstream repo + per-agent local clones.
Git is the single synchronization layer between agents.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

MAX_PUSH_RETRIES = 3


class GitSyncError(Exception):
    """Raised on unrecoverable git sync failures."""


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    log.debug("git: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        log.error("git failed: %s\nstderr: %s", " ".join(cmd), result.stderr.strip())
        raise GitSyncError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result


# ── Upstream Setup ──────────────────────────────────────────────────────────


def create_bare_repo(path: Path) -> Path:
    """Create a bare git repo at the given path."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--bare"], cwd=path)
    log.info("Created bare repo at %s", path)
    return path


def push_to_upstream(project_dir: Path, upstream: Path, branch: str = "main") -> None:
    """Push current project state to the bare upstream repo."""
    # Add upstream as a remote if not already set
    result = _run(["git", "remote"], cwd=project_dir, check=False)
    if "swarm-upstream" not in result.stdout:
        _run(["git", "remote", "add", "swarm-upstream", str(upstream)], cwd=project_dir)

    _run(["git", "push", "swarm-upstream", branch], cwd=project_dir)
    log.info("Pushed %s to upstream", branch)


def verify_upstream(upstream: Path, branch: str = "main") -> bool:
    """Verify the bare repo is valid and has commits."""
    # Try the specific branch first, then fall back to HEAD
    for ref in [branch, "HEAD"]:
        result = _run(
            ["git", "rev-list", "--count", ref],
            cwd=upstream,
            check=False,
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            if count > 0:
                return True
    return False


# ── Agent Clone ─────────────────────────────────────────────────────────────


def clone_for_agent(
    upstream: Path,
    workspace: Path,
    agent_id: str,
    branch: str = "main",
) -> Path:
    """Clone from bare upstream into agent workspace."""
    if workspace.exists():
        log.warning("Workspace %s already exists, reusing", workspace)
        return workspace

    _run(
        ["git", "clone", "--branch", branch, str(upstream), str(workspace)],
        cwd=upstream.parent,
    )

    # Configure git identity for this agent
    _run(["git", "config", "user.name", f"swarm-agent-{agent_id}"], cwd=workspace)
    _run(["git", "config", "user.email", f"agent-{agent_id}@swarm.local"], cwd=workspace)

    log.info("Cloned upstream to %s for agent %s", workspace, agent_id)
    return workspace


# ── Sync Protocol ───────────────────────────────────────────────────────────


def sync_pull(workspace: Path, branch: str = "main") -> bool:
    """Pull and rebase from upstream. Returns True on success."""
    result = _run(
        ["git", "pull", "origin", branch, "--rebase"],
        cwd=workspace,
        check=False,
    )

    if result.returncode == 0:
        return True

    # Conflict during rebase — attempt abort and reset
    log.warning("Rebase conflict in %s, aborting rebase", workspace)
    _run(["git", "rebase", "--abort"], cwd=workspace, check=False)

    # Reset to upstream state
    _run(["git", "fetch", "origin"], cwd=workspace)
    _run(["git", "reset", "--hard", f"origin/{branch}"], cwd=workspace)
    log.warning("Reset workspace %s to origin/%s after conflict", workspace, branch)
    return False


def sync_push(workspace: Path, branch: str = "main") -> bool:
    """Push to upstream with retry on failure (another agent may have pushed)."""
    for attempt in range(1, MAX_PUSH_RETRIES + 1):
        result = _run(
            ["git", "push", "origin", branch],
            cwd=workspace,
            check=False,
        )
        if result.returncode == 0:
            return True

        log.warning(
            "Push failed (attempt %d/%d) for %s: %s",
            attempt, MAX_PUSH_RETRIES, workspace, result.stderr.strip(),
        )

        if attempt < MAX_PUSH_RETRIES:
            # Pull and rebase, then retry
            sync_pull(workspace, branch)

    log.error("Push failed after %d retries for %s", MAX_PUSH_RETRIES, workspace)
    return False


def sync_status(workspace: Path, branch: str = "main") -> dict[str, int]:
    """Return commits ahead/behind upstream."""
    _run(["git", "fetch", "origin"], cwd=workspace)

    result = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
        cwd=workspace,
    )
    parts = result.stdout.strip().split()
    ahead = int(parts[0]) if len(parts) >= 1 else 0
    behind = int(parts[1]) if len(parts) >= 2 else 0
    return {"ahead": ahead, "behind": behind}


# ── Pre-Push Test Gate ──────────────────────────────────────────────────────


def run_test_gate(workspace: Path, test_command: str) -> bool:
    """Run tests before allowing a push. Returns True if tests pass."""
    log.info("Running test gate: %s", test_command)
    result = subprocess.run(
        test_command,
        shell=True,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        log.error("Test gate FAILED:\n%s", result.stdout[-2000:] if result.stdout else result.stderr[-2000:])
        return False
    log.info("Test gate passed")
    return True


def gated_push(workspace: Path, branch: str, test_command: str) -> bool:
    """Run tests, then push if they pass."""
    if not run_test_gate(workspace, test_command):
        return False
    return sync_push(workspace, branch)
