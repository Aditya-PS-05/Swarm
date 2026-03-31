"""Agent role definitions and assignment.

Roles determine what each agent focuses on. Different roles get
different prompt instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from swarm.config import ModelsConfig, RolesConfig


class RoleType(str, Enum):
    BUILDER = "builder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    DOCUMENTER = "documenter"
    FIXER = "fixer"


@dataclass
class AgentRole:
    agent_id: str
    role: RoleType
    description: str


# Role descriptions used in prompt generation
ROLE_DESCRIPTIONS: dict[RoleType, str] = {
    RoleType.BUILDER: (
        "You are a BUILDER agent. Your job is to implement features from the task list. "
        "Pick one task, implement it fully with tests, and push. Focus on writing correct, "
        "well-tested code. Do not refactor or clean up unrelated code."
    ),
    RoleType.TESTER: (
        "You are a TESTER agent. Your job is to increase test coverage. Read existing code, "
        "find untested paths, and write tests. Run coverage reports. Do not change "
        "production code unless a test reveals a bug."
    ),
    RoleType.REVIEWER: (
        "You are a REVIEWER agent. Your job is to improve code quality. Find duplicated code, "
        "simplify complex functions, ensure naming consistency, and remove dead code. "
        "Do not add new features. Focus on making existing code better."
    ),
    RoleType.DOCUMENTER: (
        "You are a DOCUMENTER agent. Your job is to keep documentation accurate. Update README, "
        "design docs, and inline comments to match the current code. Do not change "
        "functionality — only documentation."
    ),
    RoleType.FIXER: (
        "You are a FIXER agent. Your job is to fix failing tests and bugs. Run the full test "
        "suite, pick a failure, and fix it. Your goal is to turn CI red into green. "
        "Do not add new features."
    ),
}


def assign_roles(agent_count: int, roles_config: RolesConfig) -> list[AgentRole]:
    """Assign roles to agents based on config.

    Fills builder, tester, and reviewer slots from config.
    Any remaining agents become additional builders.
    """
    assignments: list[AgentRole] = []
    agent_idx = 0

    # Assign builders
    for _ in range(roles_config.builders):
        if agent_idx >= agent_count:
            break
        assignments.append(AgentRole(
            agent_id=str(agent_idx + 1),
            role=RoleType.BUILDER,
            description=ROLE_DESCRIPTIONS[RoleType.BUILDER],
        ))
        agent_idx += 1

    # Assign testers
    for _ in range(roles_config.tester):
        if agent_idx >= agent_count:
            break
        assignments.append(AgentRole(
            agent_id=str(agent_idx + 1),
            role=RoleType.TESTER,
            description=ROLE_DESCRIPTIONS[RoleType.TESTER],
        ))
        agent_idx += 1

    # Assign reviewers
    for _ in range(roles_config.reviewer):
        if agent_idx >= agent_count:
            break
        assignments.append(AgentRole(
            agent_id=str(agent_idx + 1),
            role=RoleType.REVIEWER,
            description=ROLE_DESCRIPTIONS[RoleType.REVIEWER],
        ))
        agent_idx += 1

    # Remaining agents become builders
    while agent_idx < agent_count:
        assignments.append(AgentRole(
            agent_id=str(agent_idx + 1),
            role=RoleType.BUILDER,
            description=ROLE_DESCRIPTIONS[RoleType.BUILDER],
        ))
        agent_idx += 1

    return assignments


def get_role_description(role: RoleType) -> str:
    """Get the prompt description for a role."""
    return ROLE_DESCRIPTIONS[role]


def resolve_model_for_role(
    role: RoleType,
    default_model: str,
    models_config: ModelsConfig,
) -> str:
    """Get the model for a role, using per-role override if configured."""
    role_model_map = {
        RoleType.BUILDER: models_config.builders,
        RoleType.TESTER: models_config.tester,
        RoleType.REVIEWER: models_config.reviewer,
        RoleType.DOCUMENTER: models_config.documenter,
        RoleType.FIXER: models_config.fixer,
    }
    override = role_model_map.get(role, "")
    return override if override else default_model
