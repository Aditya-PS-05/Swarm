"""Project analyzer — scans a repo to understand language, tasks, tests, and structure."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Extension → language mapping
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
}

# Package manager → language
PACKAGE_MANAGERS: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "Cargo.toml": "rust",
    "package.json": "javascript",
    "go.mod": "go",
    "CMakeLists.txt": "c",
    "Makefile": "c",
    "pom.xml": "java",
    "build.gradle": "java",
    "Gemfile": "ruby",
    "Package.swift": "swift",
}

# Test framework detection: (config file, framework name, default command)
TEST_FRAMEWORKS: list[tuple[str, str, str]] = [
    ("pyproject.toml", "pytest", "pytest"),
    ("pytest.ini", "pytest", "pytest"),
    ("setup.cfg", "pytest", "pytest"),
    ("Cargo.toml", "cargo-test", "cargo test"),
    ("package.json", "jest", "npm test"),
    ("go.mod", "go-test", "go test ./..."),
    ("CMakeLists.txt", "ctest", "ctest"),
]

TEST_DIRS = ("tests", "test", "spec", "__tests__", "testing")

# Inline task markers
TASK_MARKERS = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b:?\s*(.*)", re.IGNORECASE)


@dataclass
class Task:
    text: str
    source: str  # file path or "TODO.md"
    section: str = ""
    priority: int = 0  # lower = higher priority


@dataclass
class ProjectSummary:
    language: str = "unknown"
    package_manager: str | None = None
    test_framework: str | None = None
    test_command: str | None = None
    test_dir: str | None = None
    test_file_count: int = 0
    tasks: list[Task] = field(default_factory=list)
    total_files: int = 0
    directory_structure: str = ""


def detect_language(project_dir: Path) -> tuple[str, str | None]:
    """Detect primary language from file extensions and package managers."""
    # Check package managers first (more reliable)
    for pm_file, lang in PACKAGE_MANAGERS.items():
        if (project_dir / pm_file).exists():
            return lang, pm_file

    # Fall back to file extension counting
    counter: Counter[str] = Counter()
    for f in project_dir.rglob("*"):
        if f.is_file() and not any(p.startswith(".") for p in f.parts):
            ext = f.suffix.lower()
            if ext in EXTENSION_MAP:
                counter[EXTENSION_MAP[ext]] += 1

    if counter:
        return counter.most_common(1)[0][0], None

    return "unknown", None


def detect_test_framework(project_dir: Path, _language: str = "") -> tuple[str | None, str | None]:
    """Detect test framework and return (framework_name, test_command)."""
    for config_file, framework, command in TEST_FRAMEWORKS:
        if (project_dir / config_file).exists():
            # For package.json, check if jest/vitest/mocha is in devDependencies
            if config_file == "package.json":
                content = (project_dir / config_file).read_text()
                if "jest" in content:
                    return "jest", "npx jest"
                if "vitest" in content:
                    return "vitest", "npx vitest run"
                if "mocha" in content:
                    return "mocha", "npx mocha"
                return "npm-test", "npm test"
            return framework, command
    return None, None


def discover_tests(project_dir: Path) -> tuple[str | None, int]:
    """Find test directory and count test files."""
    for test_dir_name in TEST_DIRS:
        test_dir = project_dir / test_dir_name
        if test_dir.is_dir():
            test_files = list(test_dir.rglob("test_*.py")) + list(test_dir.rglob("*_test.py"))
            test_files += list(test_dir.rglob("test_*.rs"))
            test_files += list(test_dir.rglob("*_test.go"))
            test_files += list(test_dir.rglob("*.test.js")) + list(test_dir.rglob("*.test.ts"))
            test_files += list(test_dir.rglob("*.spec.js")) + list(test_dir.rglob("*.spec.ts"))
            return test_dir_name, len(test_files)
    return None, 0


def parse_task_file(file_path: Path) -> list[Task]:
    """Parse a TODO.md / TASKS.md for unchecked `- [ ]` items."""
    if not file_path.is_file():
        return []

    tasks: list[Task] = []
    current_section = ""
    priority = 0

    for line in file_path.read_text().splitlines():
        # Track sections (## headings)
        heading = re.match(r"^#{1,4}\s+(.+)", line)
        if heading:
            current_section = heading.group(1).strip()
            continue

        # Find unchecked items
        unchecked = re.match(r"^\s*-\s*\[ \]\s+(.+)", line)
        if unchecked:
            text = unchecked.group(1).strip()
            tasks.append(Task(
                text=text,
                source=str(file_path.name),
                section=current_section,
                priority=priority,
            ))
            priority += 1

    return tasks


def parse_inline_tasks(project_dir: Path) -> list[Task]:
    """Scan source files for TODO/FIXME/HACK comments."""
    tasks: list[Task] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"}

    for f in project_dir.rglob("*"):
        if f.is_file() and f.suffix in EXTENSION_MAP:
            if any(skip in f.parts for skip in skip_dirs):
                continue
            try:
                content = f.read_text(errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                match = TASK_MARKERS.search(line)
                if match:
                    marker, text = match.group(1), match.group(2).strip()
                    priority = 0 if marker.upper() == "FIXME" else 1
                    tasks.append(Task(
                        text=f"{marker.upper()}: {text}" if text else marker.upper(),
                        source=f"{f.relative_to(project_dir)}:{line_num}",
                        section="inline",
                        priority=priority,
                    ))
    return tasks


def build_directory_tree(project_dir: Path, max_depth: int = 3) -> str:
    """Build a simple directory tree string."""
    lines: list[str] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".omc"}

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        dirs = [e for e in entries if e.is_dir() and e.name not in skip_dirs]
        files = [e for e in entries if e.is_file()]

        for i, d in enumerate(dirs):
            connector = "|-- " if i < len(dirs) - 1 or files else "`-- "
            lines.append(f"{prefix}{connector}{d.name}/")
            extension = "|   " if i < len(dirs) - 1 or files else "    "
            _walk(d, prefix + extension, depth + 1)

        for i, f in enumerate(files):
            connector = "`-- " if i == len(files) - 1 else "|-- "
            lines.append(f"{prefix}{connector}{f.name}")

    lines.append(f"{project_dir.name}/")
    _walk(project_dir, "", 0)
    return "\n".join(lines)


def analyze_project(project_dir: Path, task_source: str = "TODO.md") -> ProjectSummary:
    """Run full project analysis and return a summary."""
    language, package_manager = detect_language(project_dir)
    test_framework, test_command = detect_test_framework(project_dir, language)
    test_dir, test_file_count = discover_tests(project_dir)

    # Gather tasks
    tasks: list[Task] = []
    task_file = project_dir / task_source
    tasks.extend(parse_task_file(task_file))
    tasks.extend(parse_inline_tasks(project_dir))
    tasks.sort(key=lambda t: t.priority)

    # Count files
    total_files = sum(
        1
        for f in project_dir.rglob("*")
        if f.is_file() and not any(p.startswith(".") for p in f.relative_to(project_dir).parts)
    )

    directory_structure = build_directory_tree(project_dir)

    return ProjectSummary(
        language=language,
        package_manager=package_manager,
        test_framework=test_framework,
        test_command=test_command,
        test_dir=test_dir,
        test_file_count=test_file_count,
        tasks=tasks,
        total_files=total_files,
        directory_structure=directory_structure,
    )


def generate_summary_markdown(summary: ProjectSummary) -> str:
    """Generate SWARM_PROJECT_SUMMARY.md content."""
    lines = [
        "# Project Summary (auto-generated by swarm)",
        "",
        f"**Language**: {summary.language}",
        f"**Package Manager**: {summary.package_manager or 'none detected'}",
        f"**Test Framework**: {summary.test_framework or 'none detected'}",
        f"**Test Command**: `{summary.test_command}`" if summary.test_command else "**Test Command**: not configured",
        f"**Test Directory**: {summary.test_dir or 'none found'}",
        f"**Test Files**: {summary.test_file_count}",
        f"**Total Files**: {summary.total_files}",
        "",
        "## Directory Structure",
        "```",
        summary.directory_structure,
        "```",
        "",
        f"## Tasks ({len(summary.tasks)} total)",
        "",
    ]

    if summary.tasks:
        current_section = ""
        for task in summary.tasks:
            if task.section and task.section != current_section:
                current_section = task.section
                lines.append(f"### {current_section}")
            lines.append(f"- [ ] {task.text} ({task.source})")
    else:
        lines.append("No tasks found.")

    lines.append("")
    return "\n".join(lines)
