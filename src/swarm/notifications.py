"""Webhooks & notifications — Slack, Discord, and generic webhook support.

Sends notifications on key events:
- Agent stuck (no commits in >15 minutes)
- Cost limit approaching (>80% of budget)
- Cost limit exceeded (agents killed)
- All tasks complete
- Agent quarantined
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from urllib.error import URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class EventType(str, Enum):
    AGENT_STUCK = "agent_stuck"
    COST_WARNING = "cost_warning"
    COST_EXCEEDED = "cost_exceeded"
    TASKS_COMPLETE = "tasks_complete"
    AGENT_QUARANTINED = "agent_quarantined"
    SWARM_STARTED = "swarm_started"
    SWARM_STOPPED = "swarm_stopped"


@dataclass
class NotificationConfig:
    webhook_url: str = ""
    slack_webhook: str = ""
    discord_webhook: str = ""
    enabled_events: list[str] = field(default_factory=lambda: [e.value for e in EventType])


@dataclass
class Event:
    event_type: EventType
    message: str
    details: dict = field(default_factory=dict)


def _post_json(url: str, data: dict, timeout: int = 10) -> bool:
    """POST JSON to a URL. Returns True on success."""
    try:
        req = Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (URLError, OSError, ValueError) as e:
        log.warning("Failed to send notification to %s: %s", url, e)
        return False


# ── Generic Webhook ─────────────────────────────────────────────────────────


def send_webhook(url: str, event: Event) -> bool:
    """Send an event to a generic webhook endpoint."""
    payload = {
        "event": event.event_type.value,
        "message": event.message,
        "details": event.details,
    }
    return _post_json(url, payload)


# ── Slack ───────────────────────────────────────────────────────────────────


def send_slack(webhook_url: str, event: Event) -> bool:
    """Send a notification to Slack via incoming webhook."""
    emoji = {
        EventType.AGENT_STUCK: ":warning:",
        EventType.COST_WARNING: ":money_with_wings:",
        EventType.COST_EXCEEDED: ":rotating_light:",
        EventType.TASKS_COMPLETE: ":white_check_mark:",
        EventType.AGENT_QUARANTINED: ":no_entry:",
        EventType.SWARM_STARTED: ":rocket:",
        EventType.SWARM_STOPPED: ":stop_sign:",
    }
    icon = emoji.get(event.event_type, ":bee:")

    payload = {
        "text": f"{icon} *Swarm AI* — {event.message}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *{event.event_type.value.replace('_', ' ').title()}*\n{event.message}",
                },
            },
        ],
    }

    if event.details:
        detail_lines = "\n".join(f"• *{k}*: {v}" for k, v in event.details.items())
        payload["blocks"].append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail_lines},
        })

    return _post_json(webhook_url, payload)


# ── Discord ─────────────────────────────────────────────────────────────────


def send_discord(webhook_url: str, event: Event) -> bool:
    """Send a notification to Discord via webhook."""
    color_map = {
        EventType.AGENT_STUCK: 0xFFA500,       # orange
        EventType.COST_WARNING: 0xFFFF00,       # yellow
        EventType.COST_EXCEEDED: 0xFF0000,      # red
        EventType.TASKS_COMPLETE: 0x00FF00,     # green
        EventType.AGENT_QUARANTINED: 0xFF0000,  # red
        EventType.SWARM_STARTED: 0x0099FF,      # blue
        EventType.SWARM_STOPPED: 0x808080,      # gray
    }

    embed = {
        "title": event.event_type.value.replace("_", " ").title(),
        "description": event.message,
        "color": color_map.get(event.event_type, 0x808080),
    }

    if event.details:
        embed["fields"] = [
            {"name": k, "value": str(v), "inline": True}
            for k, v in event.details.items()
        ]

    payload = {
        "username": "Swarm AI",
        "embeds": [embed],
    }

    return _post_json(webhook_url, payload)


# ── Unified notify ──────────────────────────────────────────────────────────


def notify(config: NotificationConfig, event: Event) -> None:
    """Send notification to all configured channels."""
    if event.event_type.value not in config.enabled_events:
        return

    if config.webhook_url:
        send_webhook(config.webhook_url, event)

    if config.slack_webhook:
        send_slack(config.slack_webhook, event)

    if config.discord_webhook:
        send_discord(config.discord_webhook, event)


def notify_agent_stuck(config: NotificationConfig, agent_id: str) -> None:
    notify(config, Event(
        EventType.AGENT_STUCK,
        f"Agent {agent_id} appears stuck — no commits in >15 minutes",
        {"agent_id": agent_id},
    ))


def notify_cost_warning(config: NotificationConfig, current: float, limit: float) -> None:
    notify(config, Event(
        EventType.COST_WARNING,
        f"Cost approaching limit: ${current:.2f} / ${limit:.2f} ({current/limit*100:.0f}%)",
        {"current_cost": f"${current:.2f}", "limit": f"${limit:.2f}"},
    ))


def notify_cost_exceeded(config: NotificationConfig, current: float, limit: float) -> None:
    notify(config, Event(
        EventType.COST_EXCEEDED,
        f"COST LIMIT EXCEEDED: ${current:.2f} >= ${limit:.2f} — agents killed",
        {"current_cost": f"${current:.2f}", "limit": f"${limit:.2f}"},
    ))


def notify_tasks_complete(config: NotificationConfig, total: int) -> None:
    notify(config, Event(
        EventType.TASKS_COMPLETE,
        f"All {total} tasks completed!",
        {"total_tasks": str(total)},
    ))


def notify_swarm_started(config: NotificationConfig, agent_count: int, project: str) -> None:
    notify(config, Event(
        EventType.SWARM_STARTED,
        f"Swarm started with {agent_count} agents on {project}",
        {"agents": str(agent_count), "project": project},
    ))


def notify_swarm_stopped(config: NotificationConfig, agent_count: int) -> None:
    notify(config, Event(
        EventType.SWARM_STOPPED,
        f"Swarm stopped — {agent_count} agents shut down",
        {"agents": str(agent_count)},
    ))
