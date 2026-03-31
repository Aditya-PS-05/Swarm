"""Tests for swarm.analyzer — language detection, task parsing, test discovery."""

from __future__ import annotations

from pathlib import Path

from swarm.analyzer import (
    Task,
    analyze_project,
    detect_language,
    detect_test_framework,
    discover_tests,
    generate_summary_markdown,
    parse_inline_tasks,
    parse_task_file,
)


class TestDetectLanguage:
    def test_python_from_pyproject(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        lang, pm = detect_language(tmp_path)
        assert lang == "python"
        assert pm == "pyproject.toml"

    def test_rust_from_cargo(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        lang, pm = detect_language(tmp_path)
        assert lang == "rust"
        assert pm == "Cargo.toml"

    def test_js_from_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{}")
        lang, pm = detect_language(tmp_path)
        assert lang == "javascript"
        assert pm == "package.json"

    def test_go_from_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text("module example\n")
        lang, pm = detect_language(tmp_path)
        assert lang == "go"
        assert pm == "go.mod"

    def test_fallback_to_extensions(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("")
        (tmp_path / "utils.py").write_text("")
        lang, pm = detect_language(tmp_path)
        assert lang == "python"
        assert pm is None

    def test_unknown_if_empty(self, tmp_path: Path):
        lang, pm = detect_language(tmp_path)
        assert lang == "unknown"
        assert pm is None


class TestDetectTestFramework:
    def test_pytest(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
        fw, cmd = detect_test_framework(tmp_path)
        assert fw == "pytest"
        assert cmd == "pytest"

    def test_cargo_test(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        fw, cmd = detect_test_framework(tmp_path)
        assert fw == "cargo-test"
        assert cmd == "cargo test"

    def test_none_if_no_config(self, tmp_path: Path):
        fw, cmd = detect_test_framework(tmp_path)
        assert fw is None
        assert cmd is None


class TestDiscoverTests:
    def test_finds_tests_dir(self, tmp_path: Path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("")
        (tests / "test_utils.py").write_text("")
        dirname, count = discover_tests(tmp_path)
        assert dirname == "tests"
        assert count == 2

    def test_no_tests_dir(self, tmp_path: Path):
        dirname, count = discover_tests(tmp_path)
        assert dirname is None
        assert count == 0


class TestParseTaskFile:
    def test_parse_unchecked_items(self, tmp_path: Path):
        todo = tmp_path / "TODO.md"
        todo.write_text(
            "# Tasks\n"
            "## Section A\n"
            "- [ ] Task one\n"
            "- [x] Done task\n"
            "- [ ] Task two\n"
        )
        tasks = parse_task_file(todo)
        assert len(tasks) == 2
        assert tasks[0].text == "Task one"
        assert tasks[0].section == "Section A"
        assert tasks[1].text == "Task two"

    def test_missing_file(self, tmp_path: Path):
        tasks = parse_task_file(tmp_path / "nope.md")
        assert tasks == []


class TestParseInlineTasks:
    def test_finds_todo_comments(self, tmp_path: Path):
        (tmp_path / "main.py").write_text(
            "# TODO: fix this\n"
            "x = 1  # FIXME: broken\n"
            "# normal comment\n"
        )
        tasks = parse_inline_tasks(tmp_path)
        assert len(tasks) == 2
        markers = {t.text.split(":")[0] for t in tasks}
        assert "TODO" in markers
        assert "FIXME" in markers


class TestAnalyzeProject:
    def test_full_analysis(self, tmp_project: Path):
        summary = analyze_project(tmp_project)
        assert summary.total_files > 0


class TestGenerateSummaryMarkdown:
    def test_generates_markdown(self, tmp_project: Path):
        summary = analyze_project(tmp_project)
        md = generate_summary_markdown(summary)
        assert "# Project Summary" in md
        assert "Language" in md
