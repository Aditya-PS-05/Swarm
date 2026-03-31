"""Shared test fixtures for swarm tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory for testing."""
    (tmp_path / "README.md").write_text("# Test Project\n")
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_ok(): assert True\n")
    return tmp_path


@pytest.fixture
def tmp_swarm_toml(tmp_project: Path) -> Path:
    """Create a minimal swarm.toml in a project directory."""
    config = tmp_project / "swarm.toml"
    config.write_text(
        '[project]\nname = "test-project"\npath = "."\n\n'
        "[agents]\ncount = 2\n"
    )
    return config
