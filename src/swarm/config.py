"""Configuration system for Swarm — loads and validates swarm.toml."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class ProjectConfig:
    name: str = "untitled"
    path: str = "."


@dataclass
class RolesConfig:
    builders: int = 2
    tester: int = 1
    reviewer: int = 1


@dataclass
class ModelsConfig:
    """Per-role model overrides. If set, overrides agents.model for that role."""
    builders: str = ""
    tester: str = ""
    reviewer: str = ""
    documenter: str = ""
    fixer: str = ""


@dataclass
class AgentsConfig:
    count: int = 4
    model: str = "claude-opus-4-6"
    timeout_minutes: int = 30
    roles: RolesConfig = field(default_factory=RolesConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)


@dataclass
class GitConfig:
    upstream: str = ".swarm/upstream.git"
    branch: str = "main"
    auto_resolve_conflicts: bool = True


@dataclass
class TestsConfig:
    command: str = "pytest"
    fast_command: str = "pytest -x --randomly-seed={agent_id} -k 'not slow'"
    gate_push: bool = True


@dataclass
class TasksConfig:
    source: str = "TODO.md"
    lock_dir: str = "current_tasks"


@dataclass
class LimitsConfig:
    max_cost_usd: float = 50.0
    max_sessions: int = 100


@dataclass
class SwarmConfig:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    git: GitConfig = field(default_factory=GitConfig)
    tests: TestsConfig = field(default_factory=TestsConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SwarmConfig:
        """Build a SwarmConfig from a parsed TOML dict, applying defaults for missing keys."""
        cfg = SwarmConfig()

        if "project" in data:
            p = data["project"]
            cfg.project = ProjectConfig(
                name=p.get("name", cfg.project.name),
                path=p.get("path", cfg.project.path),
            )

        if "agents" in data:
            a = data["agents"]
            roles_data = a.get("roles", {})
            models_data = a.get("models", {})
            cfg.agents = AgentsConfig(
                count=a.get("count", cfg.agents.count),
                model=a.get("model", cfg.agents.model),
                timeout_minutes=a.get("timeout_minutes", cfg.agents.timeout_minutes),
                roles=RolesConfig(
                    builders=roles_data.get("builders", cfg.agents.roles.builders),
                    tester=roles_data.get("tester", cfg.agents.roles.tester),
                    reviewer=roles_data.get("reviewer", cfg.agents.roles.reviewer),
                ),
                models=ModelsConfig(
                    builders=models_data.get("builders", ""),
                    tester=models_data.get("tester", ""),
                    reviewer=models_data.get("reviewer", ""),
                    documenter=models_data.get("documenter", ""),
                    fixer=models_data.get("fixer", ""),
                ),
            )

        if "git" in data:
            g = data["git"]
            cfg.git = GitConfig(
                upstream=g.get("upstream", cfg.git.upstream),
                branch=g.get("branch", cfg.git.branch),
                auto_resolve_conflicts=g.get(
                    "auto_resolve_conflicts", cfg.git.auto_resolve_conflicts
                ),
            )

        if "tests" in data:
            t = data["tests"]
            cfg.tests = TestsConfig(
                command=t.get("command", cfg.tests.command),
                fast_command=t.get("fast_command", cfg.tests.fast_command),
                gate_push=t.get("gate_push", cfg.tests.gate_push),
            )

        if "tasks" in data:
            tk = data["tasks"]
            cfg.tasks = TasksConfig(
                source=tk.get("source", cfg.tasks.source),
                lock_dir=tk.get("lock_dir", cfg.tasks.lock_dir),
            )

        if "limits" in data:
            lm = data["limits"]
            cfg.limits = LimitsConfig(
                max_cost_usd=lm.get("max_cost_usd", cfg.limits.max_cost_usd),
                max_sessions=lm.get("max_sessions", cfg.limits.max_sessions),
            )

        return cfg


class ConfigError(Exception):
    """Raised when config is invalid or not found."""


def find_config(project_dir: Path, override: Path | None = None) -> Path:
    """Locate the config file. Priority: --config override > swarm.toml > .swarm.toml."""
    if override is not None:
        if not override.is_file():
            raise ConfigError(f"Config file not found: {override}")
        return override

    for name in ("swarm.toml", ".swarm.toml"):
        candidate = project_dir / name
        if candidate.is_file():
            return candidate

    raise ConfigError(
        f"No swarm.toml or .swarm.toml found in {project_dir}. Run 'swarm init' first."
    )


def load_config(project_dir: Path, override: Path | None = None) -> SwarmConfig:
    """Load, parse, and validate the swarm config."""
    config_path = find_config(project_dir, override)
    raw = config_path.read_bytes()
    data = tomllib.loads(raw.decode())
    cfg = SwarmConfig.from_dict(data)
    validate_config(cfg, project_dir)
    return cfg


def validate_config(cfg: SwarmConfig, project_dir: Path) -> None:
    """Validate config values."""
    if cfg.agents.count < 1:
        raise ConfigError("agents.count must be >= 1")

    if cfg.agents.timeout_minutes < 1:
        raise ConfigError("agents.timeout_minutes must be >= 1")

    if cfg.limits.max_cost_usd <= 0:
        raise ConfigError("limits.max_cost_usd must be > 0")

    if cfg.limits.max_sessions < 1:
        raise ConfigError("limits.max_sessions must be >= 1")

    total_roles = cfg.agents.roles.builders + cfg.agents.roles.tester + cfg.agents.roles.reviewer
    if total_roles > cfg.agents.count:
        raise ConfigError(
            f"Total role slots ({total_roles}) exceed agent count ({cfg.agents.count}). "
            "Reduce role counts or increase agents.count."
        )

    # Validate string fields against injection
    if not re.match(r"^[a-zA-Z0-9._/-]+$", cfg.git.branch):
        raise ConfigError(f"Invalid branch name: {cfg.git.branch!r}")

    if not re.match(r"^[a-zA-Z0-9._-]+$", cfg.agents.model):
        raise ConfigError(f"Invalid model name: {cfg.agents.model!r}")

    dangerous_chars = set(";|&$`")
    for cmd_name, cmd_val in [
        ("tests.command", cfg.tests.command),
        ("tests.fast_command", cfg.tests.fast_command),
    ]:
        if dangerous_chars & set(cmd_val):
            raise ConfigError(
                f"{cmd_name} contains dangerous shell characters: {cmd_val!r}"
            )

    project_path = Path(cfg.project.path)
    if not project_path.is_absolute():
        project_path = project_dir / project_path
    if not project_path.is_dir():
        raise ConfigError(f"Project path does not exist: {project_path}")
