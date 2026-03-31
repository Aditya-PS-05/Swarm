"""Smart task discovery — priority scoring, test failure parsing, GitHub Issues.

Priority levels (lower number = higher priority):
  0: CRITICAL — failing tests, CI broken
  1: HIGH     — tasks marked "critical", "urgent", "blocker"
  2: NORMAL   — unchecked TODO items
  3: LOW      — inline TODO/FIXME comments
  4: BACKLOG  — nice-to-have, low-priority markers
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3
PRIORITY_BACKLOG = 4

HIGH_PRIORITY_MARKERS = re.compile(
    r"\b(critical|urgent|blocker|breaking|security|p0|p1)\b", re.IGNORECASE
)


@dataclass
class DiscoveredTask:
    text: str
    source: str
    priority: int = PRIORITY_NORMAL
    category: str = "todo"  # todo, test_failure, fixme, github_issue
    section: str = ""


# ── Test failure parsing ────────────────────────────────────────────────────


def parse_test_failures(test_output: str) -> list[DiscoveredTask]:
    """Parse test output to extract individual test failures as tasks."""
    tasks: list[DiscoveredTask] = []

    # pytest failures: FAILED tests/test_foo.py::test_bar - AssertionError
    for match in re.finditer(
        r"FAILED\s+(\S+?)(?:\s+-\s+(.+))?$", test_output, re.MULTILINE
    ):
        test_path = match.group(1)
        reason = match.group(2) or "unknown failure"
        tasks.append(DiscoveredTask(
            text=f"Fix failing test: {test_path} ({reason})",
            source="test_output",
            priority=PRIORITY_CRITICAL,
            category="test_failure",
        ))

    # go test failures: --- FAIL: TestFoo (0.00s)
    for match in re.finditer(
        r"--- FAIL:\s+(\S+)\s+\(", test_output, re.MULTILINE
    ):
        tasks.append(DiscoveredTask(
            text=f"Fix failing test: {match.group(1)}",
            source="test_output",
            priority=PRIORITY_CRITICAL,
            category="test_failure",
        ))

    # cargo test failures: test foo::bar ... FAILED
    for match in re.finditer(
        r"test\s+(\S+)\s+\.\.\.\s+FAILED", test_output, re.MULTILINE
    ):
        tasks.append(DiscoveredTask(
            text=f"Fix failing test: {match.group(1)}",
            source="test_output",
            priority=PRIORITY_CRITICAL,
            category="test_failure",
        ))

    # jest/vitest failures: ● Test Suite > test name
    for match in re.finditer(
        r"[●✕✗]\s+(.+)", test_output, re.MULTILINE
    ):
        tasks.append(DiscoveredTask(
            text=f"Fix failing test: {match.group(1).strip()}",
            source="test_output",
            priority=PRIORITY_CRITICAL,
            category="test_failure",
        ))

    return tasks


def run_tests_and_discover_failures(
    project_dir: Path, test_command: str
) -> list[DiscoveredTask]:
    """Run the test suite and parse failures into tasks."""
    try:
        cmd_parts = shlex.split(test_command)
    except ValueError:
        return []

    result = subprocess.run(
        cmd_parts,
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode == 0:
        return []  # All tests pass

    output = result.stdout + "\n" + result.stderr
    return parse_test_failures(output)


# ── Priority scoring ───────────────────────────────────────────────────────


def score_task_priority(text: str, section: str = "", source: str = "") -> int:
    """Assign a priority score to a task based on its text and context."""
    text_lower = text.lower()

    # Test failures are always critical
    if "failing test" in text_lower or "test fail" in text_lower:
        return PRIORITY_CRITICAL

    # Check for high-priority markers in text or section
    if HIGH_PRIORITY_MARKERS.search(text) or HIGH_PRIORITY_MARKERS.search(section):
        return PRIORITY_HIGH

    # Inline TODO/FIXME from source code (source looks like "file.py:123")
    if source == "inline" or re.search(r":\d+$", source):
        if "fixme" in text_lower:
            return PRIORITY_HIGH  # FIXME is more urgent than TODO
        return PRIORITY_LOW

    # Normal TODO items
    return PRIORITY_NORMAL


# ── TODO.md parsing with priority ──────────────────────────────────────────


def parse_task_file_with_priority(file_path: Path) -> list[DiscoveredTask]:
    """Parse a TODO.md with smart priority scoring."""
    if not file_path.is_file():
        return []

    tasks: list[DiscoveredTask] = []
    current_section = ""

    for line in file_path.read_text().splitlines():
        heading = re.match(r"^#{1,4}\s+(.+)", line)
        if heading:
            current_section = heading.group(1).strip()
            continue

        unchecked = re.match(r"^\s*-\s*\[ \]\s+(.+)", line)
        if unchecked:
            text = unchecked.group(1).strip()
            priority = score_task_priority(text, current_section)
            tasks.append(DiscoveredTask(
                text=text,
                source=str(file_path.name),
                priority=priority,
                category="todo",
                section=current_section,
            ))

    tasks.sort(key=lambda t: t.priority)
    return tasks


# ── Inline task scanning with priority ──────────────────────────────────────


TASK_MARKERS = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b:?\s*(.*)", re.IGNORECASE)


def scan_inline_tasks_with_priority(project_dir: Path) -> list[DiscoveredTask]:
    """Scan source files for TODO/FIXME/HACK with smart priority."""
    tasks: list[DiscoveredTask] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".swarm"}

    extensions = {".py", ".rs", ".go", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".h", ".java"}

    for f in project_dir.rglob("*"):
        if not f.is_file() or f.suffix not in extensions:
            continue
        if any(skip in f.parts for skip in skip_dirs):
            continue
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue
        for line_num, line in enumerate(content.splitlines(), 1):
            match = TASK_MARKERS.search(line)
            if match:
                marker, text = match.group(1).upper(), match.group(2).strip()
                source = f"{f.relative_to(project_dir)}:{line_num}"
                full_text = f"{marker}: {text}" if text else marker
                priority = score_task_priority(full_text, source=source)
                tasks.append(DiscoveredTask(
                    text=full_text,
                    source=source,
                    priority=priority,
                    category="fixme" if marker == "FIXME" else "todo",
                    section="inline",
                ))

    tasks.sort(key=lambda t: t.priority)
    return tasks


# ── GitHub Issues integration ───────────────────────────────────────────────


def fetch_github_issues(repo: str, labels: str = "") -> list[DiscoveredTask]:
    """Fetch open issues from a GitHub repo using the gh CLI.

    Args:
        repo: Owner/repo format, e.g. "user/project"
        labels: Comma-separated labels to filter by
    """
    cmd = ["gh", "issue", "list", "--repo", repo, "--state", "open", "--json",
           "number,title,labels", "--limit", "50"]
    if labels:
        cmd.extend(["--label", labels])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return []

    import json
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    tasks: list[DiscoveredTask] = []
    for issue in issues:
        label_names = [lb.get("name", "") for lb in issue.get("labels", [])]
        text = f"#{issue['number']}: {issue['title']}"

        # Priority based on labels
        priority = PRIORITY_NORMAL
        for label in label_names:
            if any(kw in label.lower() for kw in ("bug", "critical", "urgent", "p0", "p1")):
                priority = PRIORITY_HIGH
                break
            if any(kw in label.lower() for kw in ("enhancement", "feature")):
                priority = PRIORITY_NORMAL

        tasks.append(DiscoveredTask(
            text=text,
            source=f"github:{repo}",
            priority=priority,
            category="github_issue",
        ))

    tasks.sort(key=lambda t: t.priority)
    return tasks


# ── Unified discovery ──────────────────────────────────────────────────────


def discover_all_tasks(
    project_dir: Path,
    task_source: str = "TODO.md",
    test_command: str | None = None,
    github_repo: str | None = None,
) -> list[DiscoveredTask]:
    """Run all discovery sources and return a unified, priority-sorted task list."""
    all_tasks: list[DiscoveredTask] = []

    # 1. Parse TODO.md with priority scoring
    task_file = project_dir / task_source
    all_tasks.extend(parse_task_file_with_priority(task_file))

    # 2. Scan inline TODOs/FIXMEs
    all_tasks.extend(scan_inline_tasks_with_priority(project_dir))

    # 3. Parse test failures (highest priority)
    if test_command:
        all_tasks.extend(run_tests_and_discover_failures(project_dir, test_command))

    # 4. GitHub Issues
    if github_repo:
        all_tasks.extend(fetch_github_issues(github_repo))

    # Sort by priority (critical first)
    all_tasks.sort(key=lambda t: t.priority)
    return all_tasks


PRIORITY_LABELS = {
    PRIORITY_CRITICAL: "CRITICAL",
    PRIORITY_HIGH: "HIGH",
    PRIORITY_NORMAL: "NORMAL",
    PRIORITY_LOW: "LOW",
    PRIORITY_BACKLOG: "BACKLOG",
}


def format_task_list(tasks: list[DiscoveredTask], max_tasks: int = 50) -> str:
    """Format tasks as a readable markdown list with priority labels."""
    if not tasks:
        return "No tasks found."

    lines = []
    current_priority = -1

    for i, task in enumerate(tasks[:max_tasks]):
        if task.priority != current_priority:
            current_priority = task.priority
            label = PRIORITY_LABELS.get(current_priority, "UNKNOWN")
            lines.append(f"\n### Priority: {label}")

        lines.append(f"{i + 1}. [ ] {task.text} ({task.source})")

    if len(tasks) > max_tasks:
        lines.append(f"\n... and {len(tasks) - max_tasks} more tasks.")

    return "\n".join(lines)
