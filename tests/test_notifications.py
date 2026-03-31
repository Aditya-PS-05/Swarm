"""Tests for swarm.notifications — event creation and formatting."""

from __future__ import annotations

from swarm.notifications import (
    Event,
    EventType,
    NotificationConfig,
    notify,
)


class TestEvent:
    def test_create_event(self):
        event = Event(EventType.AGENT_STUCK, "Agent 1 stuck", {"agent_id": "1"})
        assert event.event_type == EventType.AGENT_STUCK
        assert event.message == "Agent 1 stuck"
        assert event.details["agent_id"] == "1"

    def test_all_event_types(self):
        for et in EventType:
            event = Event(et, f"Test {et.value}")
            assert event.event_type == et


class TestNotificationConfig:
    def test_defaults(self):
        config = NotificationConfig()
        assert config.webhook_url == ""
        assert config.slack_webhook == ""
        assert config.discord_webhook == ""
        assert len(config.enabled_events) == len(EventType)

    def test_custom_events(self):
        config = NotificationConfig(
            enabled_events=["agent_stuck", "cost_exceeded"]
        )
        assert len(config.enabled_events) == 2

    def test_with_urls(self):
        config = NotificationConfig(
            slack_webhook="https://hooks.slack.com/xxx",
            discord_webhook="https://discord.com/api/webhooks/xxx",
        )
        assert "slack" in config.slack_webhook
        assert "discord" in config.discord_webhook


class TestNotify:
    def test_skips_disabled_event(self):
        config = NotificationConfig(enabled_events=["cost_exceeded"])
        event = Event(EventType.AGENT_STUCK, "stuck")
        # Should not raise even though no webhook configured
        notify(config, event)

    def test_skips_when_no_webhooks(self):
        config = NotificationConfig()
        event = Event(EventType.SWARM_STARTED, "started")
        # Should not raise
        notify(config, event)


class TestHelperFunctions:
    def test_notify_functions_exist(self):
        from swarm.notifications import (
            notify_agent_stuck,
            notify_cost_exceeded,
            notify_cost_warning,
            notify_swarm_started,
            notify_swarm_stopped,
            notify_tasks_complete,
        )
        # Just verify they're callable
        config = NotificationConfig()
        notify_agent_stuck(config, "1")
        notify_cost_warning(config, 40.0, 50.0)
        notify_swarm_started(config, 4, "test-project")
        notify_swarm_stopped(config, 4)
        notify_tasks_complete(config, 10)
