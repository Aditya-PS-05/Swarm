"""Agent prompt generator — builds SWARM_AGENT_PROMPT.md for each agent.

This is the most critical piece: it's the only thing that tells Claude what to do.
The prompt is dynamically generated per agent with project context, role, and protocols.
"""

from __future__ import annotations

from swarm.analyzer import ProjectSummary
from swarm.roles import AgentRole

# ── Prompt sections ─────────────────────────────────────────────────────────

_TASK_SELECTION_PROTOCOL = """\
## Task Selection Protocol

1. `git pull origin {branch} --rebase` to get latest state
2. Read `{lock_dir}/` to see what tasks are currently locked by other agents
3. Pick the highest-priority **unlocked** task from `{task_source}`
4. Create a lock file `{lock_dir}/<task-slug>.lock` containing your agent ID and timestamp
5. `git add . && git commit -m "lock: <task>" && git push`
6. **If push fails** (another agent locked it first): delete your lock file, pick a different task
7. When the task is **done**: delete the lock file, commit, push
8. Never work on a task that is already locked by another agent
"""

_TESTING_PROTOCOL = """\
## Testing Protocol

1. Run fast tests after **every** change: `{fast_command}`
2. Run the full test suite **before pushing**: `{test_command}`
3. **Never push code that breaks existing tests**
4. If you broke something, fix it before doing anything else
5. If a test is flaky, note it in PROGRESS.md but still fix it
"""

_GIT_PROTOCOL = """\
## Git Protocol

1. Commit frequently with descriptive messages prefixed with your agent ID:
   `swarm(agent-{agent_id}): <what you did>`
2. Always pull before push: `git pull origin {branch} --rebase`
3. If rebase fails: `git rebase --abort`, then `git reset --hard origin/{branch}` and re-apply your changes
4. Never force push
5. Keep commits small and focused — one logical change per commit
"""

_OUTPUT_HYGIENE = """\
## Output Hygiene

Keep your context window clean — long outputs waste tokens and confuse you.

1. **Don't** print thousands of lines of test output — pipe to file, grep for errors:
   `{test_command} > /tmp/test_output.log 2>&1; grep -E "(FAIL|ERROR)" /tmp/test_output.log`
2. Use `{fast_command}` for quick iteration
3. Log everything to `agent_logs/`
4. Write `ERROR:` on the same line as the reason so grep finds it
5. When reading large files, use `head`, `tail`, or `grep` — never `cat` a 1000-line file
"""

_PROGRESS_TRACKING = """\
## Progress Tracking

1. Update `PROGRESS.md` with what you've accomplished each session
2. Note failed approaches so other agents don't repeat them
3. If you change architecture, update README
4. Format: `## Agent {agent_id} — Session <N>\\n- Did X\\n- Tried Y, failed because Z`
"""


def generate_prompt(
    agent: AgentRole,
    summary: ProjectSummary,
    project_name: str,
    branch: str = "main",
    task_source: str = "TODO.md",
    lock_dir: str = "current_tasks",
    test_command: str = "pytest",
    fast_command: str = "pytest -x -q",
) -> str:
    """Generate the full SWARM_AGENT_PROMPT.md content for an agent."""
    sections = [
        _header(agent, project_name, summary),
        _role_section(agent),
        _task_selection_protocol(branch, task_source, lock_dir),
        _testing_protocol(test_command, fast_command),
        _git_protocol(agent.agent_id, branch),
        _output_hygiene(test_command, fast_command),
        _progress_tracking(agent.agent_id),
        _task_list(summary),
    ]
    return "\n".join(sections)


def _header(agent: AgentRole, project_name: str, summary: ProjectSummary) -> str:
    lines = [
        f"# Swarm Agent Prompt — Agent {agent.agent_id} ({agent.role.value})",
        "",
        "You are an autonomous coding agent working as part of a swarm.",
        "Multiple agents are working on this project simultaneously.",
        "You communicate ONLY through git — no chat, no sockets, only files and commits.",
        "",
        "## Project Context",
        "",
        f"- **Project**: {project_name}",
        f"- **Language**: {summary.language}",
        f"- **Test framework**: {summary.test_framework or 'unknown'}",
        f"- **Test command**: `{summary.test_command or 'unknown'}`",
        f"- **Total files**: {summary.total_files}",
        f"- **Open tasks**: {len(summary.tasks)}",
        "",
    ]
    return "\n".join(lines)


def _role_section(agent: AgentRole) -> str:
    return f"## Your Role\n\n{agent.description}\n"


def _task_selection_protocol(branch: str, task_source: str, lock_dir: str) -> str:
    return _TASK_SELECTION_PROTOCOL.format(
        branch=branch,
        task_source=task_source,
        lock_dir=lock_dir,
    )


def _testing_protocol(test_command: str, fast_command: str) -> str:
    return _TESTING_PROTOCOL.format(
        test_command=test_command,
        fast_command=fast_command,
    )


def _git_protocol(agent_id: str, branch: str) -> str:
    return _GIT_PROTOCOL.format(agent_id=agent_id, branch=branch)


def _output_hygiene(test_command: str, fast_command: str) -> str:
    return _OUTPUT_HYGIENE.format(test_command=test_command, fast_command=fast_command)


def _progress_tracking(agent_id: str) -> str:
    return _PROGRESS_TRACKING.format(agent_id=agent_id)


def _task_list(summary: ProjectSummary) -> str:
    if not summary.tasks:
        return "## Tasks\n\nNo tasks found. Look for work to do by reading the codebase.\n"

    lines = ["## Current Task List", ""]
    current_section = ""
    for i, task in enumerate(summary.tasks[:50]):  # cap at 50 to avoid prompt bloat
        if task.section and task.section != current_section:
            current_section = task.section
            lines.append(f"### {current_section}")
        lines.append(f"{i + 1}. [ ] {task.text}")

    if len(summary.tasks) > 50:
        lines.append(f"\n... and {len(summary.tasks) - 50} more tasks. Check {summary.tasks[0].source} for the full list.")

    lines.append("")
    return "\n".join(lines)


def write_prompt_to_workspace(
    workspace_dir,
    agent: AgentRole,
    summary: ProjectSummary,
    project_name: str,
    branch: str = "main",
    task_source: str = "TODO.md",
    lock_dir: str = "current_tasks",
    test_command: str = "pytest",
    fast_command: str = "pytest -x -q",
) -> str:
    """Generate and write the prompt to SWARM_AGENT_PROMPT.md in workspace."""
    from pathlib import Path

    content = generate_prompt(
        agent=agent,
        summary=summary,
        project_name=project_name,
        branch=branch,
        task_source=task_source,
        lock_dir=lock_dir,
        test_command=test_command,
        fast_command=fast_command,
    )
    path = Path(workspace_dir) / "SWARM_AGENT_PROMPT.md"
    path.write_text(content)
    return str(path)
