"""Tests for swarm.prompt — prompt generation."""

from __future__ import annotations

from swarm.analyzer import ProjectSummary, Task
from swarm.prompt import generate_prompt, write_prompt_to_workspace
from swarm.roles import AgentRole, RoleType


def _make_agent(role: RoleType = RoleType.BUILDER) -> AgentRole:
    return AgentRole(agent_id="1", role=role, description=f"Test {role.value}")


def _make_summary(**kwargs) -> ProjectSummary:
    defaults = {
        "language": "python",
        "test_framework": "pytest",
        "test_command": "pytest",
        "total_files": 10,
        "tasks": [Task(text="Implement feature X", source="TODO.md", section="Features")],
    }
    defaults.update(kwargs)
    return ProjectSummary(**defaults)


class TestGeneratePrompt:
    def test_contains_project_context(self):
        prompt = generate_prompt(_make_agent(), _make_summary(), "myproject")
        assert "myproject" in prompt
        assert "python" in prompt
        assert "pytest" in prompt

    def test_contains_role(self):
        prompt = generate_prompt(_make_agent(RoleType.TESTER), _make_summary(), "proj")
        assert "Test tester" in prompt

    def test_contains_task_list(self):
        prompt = generate_prompt(_make_agent(), _make_summary(), "proj")
        assert "Implement feature X" in prompt

    def test_contains_protocols(self):
        prompt = generate_prompt(_make_agent(), _make_summary(), "proj")
        assert "Task Selection Protocol" in prompt
        assert "Testing Protocol" in prompt
        assert "Git Protocol" in prompt
        assert "Output Hygiene" in prompt
        assert "Progress Tracking" in prompt

    def test_agent_id_in_git_protocol(self):
        prompt = generate_prompt(_make_agent(), _make_summary(), "proj")
        assert "agent-1" in prompt

    def test_empty_tasks(self):
        summary = _make_summary(tasks=[])
        prompt = generate_prompt(_make_agent(), summary, "proj")
        assert "No tasks found" in prompt

    def test_many_tasks_capped(self):
        tasks = [Task(text=f"Task {i}", source="TODO.md") for i in range(100)]
        summary = _make_summary(tasks=tasks)
        prompt = generate_prompt(_make_agent(), summary, "proj")
        assert "Task 0" in prompt
        assert "Task 49" in prompt
        assert "50 more tasks" in prompt

    def test_all_roles_generate(self):
        for role_type in RoleType:
            agent = _make_agent(role_type)
            prompt = generate_prompt(agent, _make_summary(), "proj")
            assert len(prompt) > 100


class TestWritePrompt:
    def test_writes_file(self, tmp_path):
        path = write_prompt_to_workspace(
            tmp_path, _make_agent(), _make_summary(), "proj"
        )
        assert (tmp_path / "SWARM_AGENT_PROMPT.md").exists()
        assert "proj" in (tmp_path / "SWARM_AGENT_PROMPT.md").read_text()
