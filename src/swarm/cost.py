"""Cost tracker — parse token usage from agent logs, enforce limits.

Claude Code prints token usage at the end of each session.
We parse these logs to track cumulative cost across all agents.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Pricing per million tokens (as of March 2026)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}

# Patterns to match token usage in Claude Code output
TOKEN_PATTERNS = [
    # "Total tokens: 12345 input, 6789 output"
    re.compile(r"Total.*?(\d[\d,]+)\s*input.*?(\d[\d,]+)\s*output", re.IGNORECASE),
    # "Input tokens: 12345 | Output tokens: 6789"
    re.compile(r"Input.*?(\d[\d,]+).*Output.*?(\d[\d,]+)", re.IGNORECASE),
    # "tokens: {"input": 12345, "output": 6789}"
    re.compile(r'"input":\s*(\d[\d,]+).*"output":\s*(\d[\d,]+)'),
]


@dataclass
class SessionCost:
    agent_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    log_file: str = ""


@dataclass
class CostSummary:
    sessions: list[SessionCost] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    cost_by_agent: dict[str, float] = field(default_factory=dict)


def _parse_int(s: str) -> int:
    """Parse an integer that may contain commas."""
    return int(s.replace(",", ""))


def parse_token_usage(log_content: str) -> tuple[int, int]:
    """Extract input/output token counts from a log file's content."""
    for pattern in TOKEN_PATTERNS:
        match = pattern.search(log_content)
        if match:
            return _parse_int(match.group(1)), _parse_int(match.group(2))
    return 0, 0


def calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Calculate USD cost for a given token count and model."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-opus-4-6"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def scan_agent_logs(logs_dir: Path, model: str = "claude-opus-4-6") -> list[SessionCost]:
    """Scan agent_logs/ directory and parse token usage from each log."""
    if not logs_dir.is_dir():
        return []

    sessions: list[SessionCost] = []
    for log_file in sorted(logs_dir.glob("*.log")):
        # Extract agent ID from filename: "{agent_id}_session_{n}_{ts}.log"
        name_parts = log_file.stem.split("_")
        agent_id = name_parts[0] if name_parts else "unknown"

        try:
            content = log_file.read_text(errors="ignore")
        except OSError:
            continue

        input_tokens, output_tokens = parse_token_usage(content)
        if input_tokens == 0 and output_tokens == 0:
            continue

        cost = calculate_cost(input_tokens, output_tokens, model)
        sessions.append(SessionCost(
            agent_id=agent_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            log_file=log_file.name,
        ))

    return sessions


def compute_cost_summary(sessions: list[SessionCost]) -> CostSummary:
    """Aggregate session costs into a summary."""
    summary = CostSummary(sessions=sessions)

    for s in sessions:
        summary.total_input_tokens += s.input_tokens
        summary.total_output_tokens += s.output_tokens
        summary.total_cost_usd += s.cost_usd
        summary.cost_by_agent[s.agent_id] = (
            summary.cost_by_agent.get(s.agent_id, 0.0) + s.cost_usd
        )

    return summary


def check_cost_limit(summary: CostSummary, max_cost_usd: float) -> bool:
    """Check if cost limit has been exceeded. Returns True if OVER limit."""
    if summary.total_cost_usd >= max_cost_usd:
        log.critical(
            "COST LIMIT EXCEEDED: $%.2f >= $%.2f — killing all agents",
            summary.total_cost_usd,
            max_cost_usd,
        )
        return True

    # Warn at 80%
    if summary.total_cost_usd >= max_cost_usd * 0.8:
        log.warning(
            "Cost warning: $%.2f / $%.2f (%.0f%%)",
            summary.total_cost_usd,
            max_cost_usd,
            (summary.total_cost_usd / max_cost_usd) * 100,
        )

    return False
