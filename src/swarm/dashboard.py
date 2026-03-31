"""Live TUI dashboard — Textual-based real-time monitoring.

Shows per-agent status, git commit stream, cost meter, task burndown,
and agent health indicators. Updates every 2 seconds.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

from swarm.config import SwarmConfig


class AgentPanel(Static):
    """Displays status for all agents in a table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="agent-table")

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("Agent", "Role", "Status", "Task", "Last Commit", "Commits", "Sessions")


class CommitStream(Static):
    """Live feed of recent git commits."""

    def compose(self) -> ComposeResult:
        yield Static("Waiting for commits...", id="commit-log")


class CostMeter(Static):
    """Cost progress bar and summary."""

    cost_text: reactive[str] = reactive("$0.00 / $50.00")

    def compose(self) -> ComposeResult:
        yield Static(id="cost-display")

    def watch_cost_text(self, value: str) -> None:
        display = self.query_one("#cost-display", Static)
        display.update(value)


class TaskBurndown(Static):
    """Task progress: completed vs total."""

    def compose(self) -> ComposeResult:
        yield Static(id="burndown-display")


class HealthBar(Static):
    """Agent health indicators."""

    def compose(self) -> ComposeResult:
        yield Static(id="health-display")


class SwarmDashboard(App):
    """Live TUI dashboard for monitoring swarm agents."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 3;
        grid-gutter: 1;
    }

    AgentPanel {
        column-span: 2;
        height: auto;
        min-height: 10;
        border: solid $accent;
        padding: 1;
    }

    CommitStream {
        height: auto;
        min-height: 8;
        border: solid $primary;
        padding: 1;
    }

    CostMeter {
        height: auto;
        min-height: 5;
        border: solid $warning;
        padding: 1;
    }

    TaskBurndown {
        height: auto;
        min-height: 5;
        border: solid $success;
        padding: 1;
    }

    HealthBar {
        height: auto;
        min-height: 5;
        border: solid $error;
        padding: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        config: SwarmConfig,
        upstream: Path,
        lock_dir: Path,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config = config
        self.upstream = upstream
        self.lock_dir = lock_dir
        self.agent_ids = [str(i + 1) for i in range(config.agents.count)]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield AgentPanel(id="agents")
        yield CommitStream(id="commits")
        yield Vertical(
            CostMeter(id="cost"),
            TaskBurndown(id="burndown"),
            HealthBar(id="health"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Swarm AI — {self.config.project.name}"
        self.sub_title = f"{self.config.agents.count} agents | {self.config.agents.model}"
        self.set_interval(2.0, self._refresh_data)
        self._refresh_data()

    def _refresh_data(self) -> None:
        """Refresh all dashboard panels with current data."""
        self._update_agents()
        self._update_commits()
        self._update_cost()
        self._update_health()

    def _update_agents(self) -> None:
        from swarm.monitor import collect_swarm_status

        try:
            status = collect_swarm_status(
                self.upstream, self.lock_dir, self.agent_ids,
                branch=self.config.git.branch,
            )
        except Exception:
            return

        table = self.query_one("#agent-table", DataTable)
        table.clear()

        for agent in status.agents:
            status_style = {
                "healthy": "green",
                "stuck": "red bold",
                "crash-looping": "red",
                "no-commits": "yellow",
            }.get(agent.status, "white")

            table.add_row(
                agent.agent_id,
                agent.role or "-",
                Text(agent.status, style=status_style),
                agent.current_task or "-",
                (agent.last_commit_msg[:35] + "...") if len(agent.last_commit_msg) > 35 else agent.last_commit_msg or "-",
                str(agent.total_commits),
                str(agent.session_count),
            )

    def _update_commits(self) -> None:
        import subprocess

        result = subprocess.run(
            ["git", "log", "--oneline", "--author=swarm-agent-", "-15", self.config.git.branch],
            cwd=self.upstream,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return

        log_widget = self.query_one("#commit-log", Static)
        log_widget.update(result.stdout.strip())

    def _update_cost(self) -> None:
        from swarm.cost import compute_cost_summary, scan_agent_logs

        logs_dir = self.lock_dir.parent / "agent_logs"
        sessions = scan_agent_logs(logs_dir, self.config.agents.model)
        summary = compute_cost_summary(sessions)

        max_cost = self.config.limits.max_cost_usd
        pct = (summary.total_cost_usd / max_cost * 100) if max_cost > 0 else 0
        bar_width = 30
        filled = int(bar_width * min(pct, 100) / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        color = "green" if pct < 60 else "yellow" if pct < 80 else "red"
        cost_widget = self.query_one("#cost-display", Static)
        cost_widget.update(
            Text.from_markup(
                f"[bold]Cost:[/bold] ${summary.total_cost_usd:.2f} / ${max_cost:.2f}\n"
                f"[{color}]{bar}[/{color}] {pct:.0f}%\n"
                f"Sessions: {len(sessions)}"
            )
        )

    def _update_health(self) -> None:
        from swarm.monitor import collect_swarm_status, get_health_warnings

        try:
            status = collect_swarm_status(
                self.upstream, self.lock_dir, self.agent_ids,
                branch=self.config.git.branch,
            )
        except Exception:
            return

        warnings = get_health_warnings(status)
        health_widget = self.query_one("#health-display", Static)

        if not warnings:
            health_widget.update(Text("All agents healthy", style="green bold"))
        else:
            lines = []
            for w in warnings:
                lines.append(Text(f"⚠ {w}", style="yellow"))
            combined = Text("\n").join(lines)
            health_widget.update(combined)

    def action_refresh(self) -> None:
        self._refresh_data()


def run_dashboard(
    config: SwarmConfig,
    upstream: Path,
    lock_dir: Path,
) -> None:
    """Launch the TUI dashboard."""
    app = SwarmDashboard(config=config, upstream=upstream, lock_dir=lock_dir)
    app.run()
