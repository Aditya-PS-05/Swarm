"""Tests for swarm.discovery — smart task discovery and priority scoring."""

from __future__ import annotations

from pathlib import Path

from swarm.discovery import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    discover_all_tasks,
    format_task_list,
    parse_task_file_with_priority,
    parse_test_failures,
    scan_inline_tasks_with_priority,
    score_task_priority,
)


class TestPriorityScoring:
    def test_critical_keyword(self):
        assert score_task_priority("Fix critical auth bug") == PRIORITY_HIGH

    def test_urgent_keyword(self):
        assert score_task_priority("urgent: fix login") == PRIORITY_HIGH

    def test_security_keyword(self):
        assert score_task_priority("Fix security vulnerability") == PRIORITY_HIGH

    def test_normal_task(self):
        assert score_task_priority("Add caching layer") == PRIORITY_NORMAL

    def test_fixme_inline(self):
        assert score_task_priority("FIXME: broken", source="main.py:10") == PRIORITY_HIGH

    def test_todo_inline(self):
        assert score_task_priority("TODO: refactor", source="main.py:5") == PRIORITY_LOW

    def test_test_failure(self):
        assert score_task_priority("Fix failing test: test_auth") == PRIORITY_CRITICAL

    def test_section_priority(self):
        assert score_task_priority("Some task", section="Critical Bugs") == PRIORITY_HIGH


class TestTestFailureParsing:
    def test_pytest_failures(self):
        output = (
            "FAILED tests/test_auth.py::test_login - AssertionError\n"
            "FAILED tests/test_db.py::test_connect - ConnectionError\n"
        )
        tasks = parse_test_failures(output)
        assert len(tasks) == 2
        assert all(t.priority == PRIORITY_CRITICAL for t in tasks)
        assert all(t.category == "test_failure" for t in tasks)

    def test_go_failures(self):
        output = "--- FAIL: TestLogin (0.01s)\n--- FAIL: TestDB (0.02s)\n"
        tasks = parse_test_failures(output)
        assert len(tasks) == 2

    def test_cargo_failures(self):
        output = "test auth::test_login ... FAILED\ntest db::test_connect ... FAILED\n"
        tasks = parse_test_failures(output)
        assert len(tasks) == 2

    def test_no_failures(self):
        assert parse_test_failures("All tests passed!") == []


class TestTodoParsingWithPriority:
    def test_critical_section(self, tmp_path: Path):
        (tmp_path / "TODO.md").write_text(
            "## Critical Bugs\n- [ ] Fix auth crash\n## Features\n- [ ] Add search\n"
        )
        tasks = parse_task_file_with_priority(tmp_path / "TODO.md")
        assert len(tasks) == 2
        assert tasks[0].priority == PRIORITY_HIGH  # critical section
        assert tasks[1].priority == PRIORITY_NORMAL

    def test_priority_keywords_in_text(self, tmp_path: Path):
        (tmp_path / "TODO.md").write_text("# Tasks\n- [ ] urgent fix needed\n- [ ] nice to have\n")
        tasks = parse_task_file_with_priority(tmp_path / "TODO.md")
        assert tasks[0].priority == PRIORITY_HIGH
        assert tasks[1].priority == PRIORITY_NORMAL

    def test_sorted_by_priority(self, tmp_path: Path):
        (tmp_path / "TODO.md").write_text(
            "# Tasks\n- [ ] normal task\n## Security\n- [ ] fix security bug\n"
        )
        tasks = parse_task_file_with_priority(tmp_path / "TODO.md")
        assert tasks[0].priority <= tasks[-1].priority


class TestInlineScanning:
    def test_finds_fixme_and_todo(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("# FIXME: broken\nx = 1  # TODO: refactor\n")
        tasks = scan_inline_tasks_with_priority(tmp_path)
        assert len(tasks) == 2
        fixme = [t for t in tasks if "FIXME" in t.text]
        todo = [t for t in tasks if t.text.startswith("TODO")]
        assert fixme[0].priority == PRIORITY_HIGH
        assert todo[0].priority == PRIORITY_LOW


class TestUnifiedDiscovery:
    def test_merges_sources(self, tmp_path: Path):
        (tmp_path / "TODO.md").write_text("# Tasks\n- [ ] Add feature\n")
        (tmp_path / "main.py").write_text("# TODO: cleanup\n")
        tasks = discover_all_tasks(tmp_path)
        assert len(tasks) >= 2

    def test_sorted_by_priority(self, tmp_path: Path):
        (tmp_path / "TODO.md").write_text(
            "# Tasks\n- [ ] normal\n## Critical\n- [ ] urgent fix\n"
        )
        tasks = discover_all_tasks(tmp_path)
        for i in range(len(tasks) - 1):
            assert tasks[i].priority <= tasks[i + 1].priority


class TestFormatTaskList:
    def test_format_with_priorities(self):
        from swarm.discovery import DiscoveredTask

        tasks = [
            DiscoveredTask("Fix test", "test", PRIORITY_CRITICAL),
            DiscoveredTask("Add feature", "todo", PRIORITY_NORMAL),
        ]
        output = format_task_list(tasks)
        assert "CRITICAL" in output
        assert "NORMAL" in output

    def test_empty_list(self):
        assert format_task_list([]) == "No tasks found."
