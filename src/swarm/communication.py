"""Agent communication — file-based, synced via git.

Agents communicate through shared markdown files committed to the repo:
- PROGRESS.md: what each agent has accomplished
- FAILED_APPROACHES.md: what didn't work (so others avoid it)
- DECISIONS.md: architectural decisions visible to all

All communication is file-based, no sideband channels.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def _ensure_file(path: Path, header: str) -> None:
    """Create the file with a header if it doesn't exist."""
    if not path.exists():
        path.write_text(f"# {header}\n\n")


def _append_section(path: Path, section: str) -> None:
    """Append a section to a file."""
    with open(path, "a") as f:
        f.write(f"\n{section}\n")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── PROGRESS.md ─────────────────────────────────────────────────────────────


def log_progress(
    workspace: Path,
    agent_id: str,
    session: int,
    accomplishments: list[str],
) -> None:
    """Log what an agent accomplished in a session."""
    path = workspace / "PROGRESS.md"
    _ensure_file(path, "Progress Log")

    lines = [
        f"## Agent {agent_id} — Session {session} ({_timestamp()})",
    ]
    for item in accomplishments:
        lines.append(f"- {item}")

    _append_section(path, "\n".join(lines))


def get_progress(workspace: Path) -> str:
    """Read the full progress log."""
    path = workspace / "PROGRESS.md"
    if not path.is_file():
        return ""
    return path.read_text()


def get_agent_progress(workspace: Path, agent_id: str) -> list[str]:
    """Get progress entries for a specific agent."""
    content = get_progress(workspace)
    entries = []
    capture = False
    for line in content.splitlines():
        if line.startswith(f"## Agent {agent_id}"):
            capture = True
            entries.append(line)
        elif line.startswith("## Agent ") and capture:
            capture = False
        elif capture:
            entries.append(line)
    return entries


# ── FAILED_APPROACHES.md ───────────────────────────────────────────────────


def log_failed_approach(
    workspace: Path,
    agent_id: str,
    task: str,
    approach: str,
    reason: str,
) -> None:
    """Log a failed approach so other agents avoid it."""
    path = workspace / "FAILED_APPROACHES.md"
    _ensure_file(path, "Failed Approaches")

    section = (
        f"## [{_timestamp()}] Agent {agent_id} — {task}\n"
        f"**Approach:** {approach}\n"
        f"**Why it failed:** {reason}\n"
        f"**Avoid:** Do not retry this approach for this task."
    )
    _append_section(path, section)


def get_failed_approaches(workspace: Path) -> list[dict]:
    """Parse failed approaches into structured data."""
    path = workspace / "FAILED_APPROACHES.md"
    if not path.is_file():
        return []

    content = path.read_text()
    approaches = []
    current: dict | None = None

    for line in content.splitlines():
        header = re.match(r"## \[.*?\] Agent (\S+) — (.+)", line)
        if header:
            if current:
                approaches.append(current)
            current = {
                "agent_id": header.group(1),
                "task": header.group(2),
                "approach": "",
                "reason": "",
            }
        elif current:
            approach_match = re.match(r"\*\*Approach:\*\* (.+)", line)
            reason_match = re.match(r"\*\*Why it failed:\*\* (.+)", line)
            if approach_match:
                current["approach"] = approach_match.group(1)
            elif reason_match:
                current["reason"] = reason_match.group(1)

    if current:
        approaches.append(current)

    return approaches


def is_known_failure(workspace: Path, task: str, approach: str) -> bool:
    """Check if an approach for a task has already been tried and failed."""
    for entry in get_failed_approaches(workspace):
        if entry["task"] == task and approach.lower() in entry["approach"].lower():
            return True
    return False


# ── DECISIONS.md ────────────────────────────────────────────────────────────


def log_decision(
    workspace: Path,
    agent_id: str,
    title: str,
    context: str,
    decision: str,
    alternatives: list[str] | None = None,
) -> None:
    """Log an architectural decision."""
    path = workspace / "DECISIONS.md"
    _ensure_file(path, "Architectural Decisions")

    lines = [
        f"## [{_timestamp()}] {title}",
        f"**Decided by:** Agent {agent_id}",
        f"**Context:** {context}",
        f"**Decision:** {decision}",
    ]
    if alternatives:
        lines.append("**Alternatives considered:**")
        for alt in alternatives:
            lines.append(f"  - {alt}")

    _append_section(path, "\n".join(lines))


def get_decisions(workspace: Path) -> list[dict]:
    """Parse decisions into structured data."""
    path = workspace / "DECISIONS.md"
    if not path.is_file():
        return []

    content = path.read_text()
    decisions = []
    current: dict | None = None

    for line in content.splitlines():
        header = re.match(r"## \[.*?\] (.+)", line)
        if header:
            if current:
                decisions.append(current)
            current = {"title": header.group(1), "agent_id": "", "context": "", "decision": ""}
        elif current:
            agent_match = re.match(r"\*\*Decided by:\*\* Agent (\S+)", line)
            context_match = re.match(r"\*\*Context:\*\* (.+)", line)
            decision_match = re.match(r"\*\*Decision:\*\* (.+)", line)
            if agent_match:
                current["agent_id"] = agent_match.group(1)
            elif context_match:
                current["context"] = context_match.group(1)
            elif decision_match:
                current["decision"] = decision_match.group(1)

    if current:
        decisions.append(current)

    return decisions


# ── Prompt integration ──────────────────────────────────────────────────────


def generate_communication_prompt_section(workspace: Path) -> str:
    """Generate a prompt section summarizing current communication state."""
    lines = ["## Shared Knowledge (from other agents)", ""]

    # Recent progress
    progress = get_progress(workspace)
    if progress:
        recent = progress.splitlines()[-30:]  # last 30 lines
        lines.append("### Recent Progress")
        lines.extend(recent)
        lines.append("")

    # Failed approaches
    failures = get_failed_approaches(workspace)
    if failures:
        lines.append("### Known Failed Approaches (DO NOT RETRY)")
        for f in failures[-10:]:  # last 10
            lines.append(f"- **{f['task']}**: {f['approach']} — {f['reason']}")
        lines.append("")

    # Decisions
    decisions = get_decisions(workspace)
    if decisions:
        lines.append("### Architectural Decisions (FOLLOW THESE)")
        for d in decisions[-10:]:  # last 10
            lines.append(f"- **{d['title']}**: {d['decision']}")
        lines.append("")

    return "\n".join(lines)
