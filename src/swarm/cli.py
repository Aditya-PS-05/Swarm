"""Swarm CLI — powered by Typer + Rich."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from swarm import __version__

app = typer.Typer(
    name="swarm",
    help="Swarm AI — Point it at any repo. It spawns parallel Claude agents that build your project autonomously.",
    no_args_is_help=True,
)
console = Console()


# ── swarm init ──────────────────────────────────────────────────────────────


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Project directory to analyze"),
    agents: int = typer.Option(4, help="Number of agents"),
    model: str = typer.Option("claude-opus-4-6", help="Claude model to use"),
) -> None:
    """Analyze project and generate swarm.toml."""
    from swarm.analyzer import analyze_project

    project_dir = path.resolve()
    if not project_dir.is_dir():
        console.print(f"[red]Error:[/red] {project_dir} is not a directory")
        raise typer.Exit(1)

    console.print(f"[bold]Analyzing project:[/bold] {project_dir}")
    summary = analyze_project(project_dir)

    console.print(f"  Language: [cyan]{summary.language}[/cyan]")
    console.print(f"  Package manager: [cyan]{summary.package_manager or 'none'}[/cyan]")
    console.print(f"  Test framework: [cyan]{summary.test_framework or 'none'}[/cyan]")
    console.print(f"  Test command: [cyan]{summary.test_command or 'none'}[/cyan]")
    console.print(f"  Tasks found: [cyan]{len(summary.tasks)}[/cyan]")
    console.print(f"  Total files: [cyan]{summary.total_files}[/cyan]")

    # Generate swarm.toml
    config_path = project_dir / "swarm.toml"
    test_cmd = summary.test_command or "pytest"
    fast_cmd = f"{test_cmd} -x -q" if summary.test_framework else test_cmd

    config_content = f"""\
[project]
name = "{project_dir.name}"
path = "."

[agents]
count = {agents}
model = "{model}"
timeout_minutes = 30

[agents.roles]
builders = {max(1, agents - 2)}
tester = 1
reviewer = 1

[git]
upstream = ".swarm/upstream.git"
branch = "main"
auto_resolve_conflicts = true

[tests]
command = "{test_cmd}"
fast_command = "{fast_cmd}"
gate_push = true

[tasks]
source = "TODO.md"
lock_dir = "current_tasks"

[limits]
max_cost_usd = 50.0
max_sessions = 100
"""
    config_path.write_text(config_content)
    console.print(f"\n[green]Wrote {config_path}[/green]")


# ── swarm config show ───────────────────────────────────────────────────────


@app.command("config")
def config_show(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Show resolved configuration."""
    from swarm.config import load_config

    cfg = load_config(Path.cwd(), config)
    console.print("[bold]Resolved configuration:[/bold]\n")
    console.print(f"  project.name     = {cfg.project.name}")
    console.print(f"  project.path     = {cfg.project.path}")
    console.print(f"  agents.count     = {cfg.agents.count}")
    console.print(f"  agents.model     = {cfg.agents.model}")
    console.print(f"  agents.timeout   = {cfg.agents.timeout_minutes}m")
    console.print(f"  roles.builders   = {cfg.agents.roles.builders}")
    console.print(f"  roles.tester     = {cfg.agents.roles.tester}")
    console.print(f"  roles.reviewer   = {cfg.agents.roles.reviewer}")
    console.print(f"  git.upstream     = {cfg.git.upstream}")
    console.print(f"  git.branch       = {cfg.git.branch}")
    console.print(f"  tests.command    = {cfg.tests.command}")
    console.print(f"  tests.gate_push  = {cfg.tests.gate_push}")
    console.print(f"  tasks.source     = {cfg.tasks.source}")
    console.print(f"  limits.max_cost  = ${cfg.limits.max_cost_usd:.2f}")
    console.print(f"  limits.sessions  = {cfg.limits.max_sessions}")


# ── swarm run ───────────────────────────────────────────────────────────────


@app.command()
def run(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file path"),
    agents: Optional[int] = typer.Option(None, "--agents", "-n", help="Override agent count"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override model"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen"),
    _detach: bool = typer.Option(False, "--detach", "-d", help="Run in background"),
) -> None:
    """Start all agents."""
    from swarm.analyzer import analyze_project
    from swarm.config import load_config
    from swarm.containers import ContainerSpec, build_image, spawn_agent, write_docker_assets
    from swarm.git_sync import create_bare_repo, push_to_upstream
    from swarm.roles import assign_roles

    cfg = load_config(Path.cwd(), config)
    if agents:
        cfg.agents.count = agents
    if model:
        cfg.agents.model = model

    project_dir = Path(cfg.project.path).resolve()
    upstream = Path(cfg.git.upstream)

    console.print(f"[bold]Starting swarm[/bold] — {cfg.agents.count} agents, model {cfg.agents.model}")

    # 1. Analyze project
    console.print("  Analyzing project...")
    summary = analyze_project(project_dir, cfg.tasks.source)

    # 2. Set up upstream bare repo
    console.print(f"  Creating upstream repo at {upstream}...")
    if not dry_run:
        create_bare_repo(upstream)
        push_to_upstream(project_dir, upstream, cfg.git.branch)

    # 3. Assign roles
    roles = assign_roles(cfg.agents.count, cfg.agents.roles)
    for role in roles:
        console.print(f"  Agent {role.agent_id}: [cyan]{role.role.value}[/cyan]")

    # 4. Build Docker image
    console.print(f"  Building Docker image for {summary.language}...")
    if not dry_run:
        build_dir = project_dir / ".swarm" / "build"
        write_docker_assets(build_dir, summary.language)
        image_tag = build_image(build_dir, cfg.project.name)
    else:
        image_tag = f"swarm-agent:{cfg.project.name}"

    # 5. Generate prompts and spawn agents
    for role in roles:
        if dry_run:
            console.print(f"  [dim]Would spawn agent {role.agent_id} ({role.role.value})[/dim]")
            continue

        spec = ContainerSpec(
            agent_id=role.agent_id,
            role=role.role.value,
            image_name=image_tag,
            upstream_path=str(upstream),
            branch=cfg.git.branch,
            model=cfg.agents.model,
        )
        container_id = spawn_agent(spec)
        console.print(f"  [green]Spawned agent {role.agent_id}[/green] ({container_id[:12]})")

    if dry_run:
        console.print("\n[yellow]Dry run complete — no agents spawned[/yellow]")
    else:
        console.print(f"\n[green bold]Swarm running![/green bold] {cfg.agents.count} agents active")
        console.print("  Use [cyan]swarm status[/cyan] to monitor progress")
        console.print("  Use [cyan]swarm stop[/cyan] to shut down")


# ── swarm status ────────────────────────────────────────────────────────────


@app.command()
def status(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Show agent status table."""
    from swarm.config import load_config
    from swarm.monitor import collect_swarm_status, get_health_warnings

    cfg = load_config(Path.cwd(), config)
    upstream = Path(cfg.git.upstream)
    lock_dir = Path.cwd() / cfg.tasks.lock_dir

    agent_ids = [str(i + 1) for i in range(cfg.agents.count)]
    swarm_status = collect_swarm_status(upstream, lock_dir, agent_ids, branch=cfg.git.branch)

    table = Table(title="Swarm Agent Status")
    table.add_column("Agent", style="bold")
    table.add_column("Role", style="cyan")
    table.add_column("Status")
    table.add_column("Current Task")
    table.add_column("Last Commit")
    table.add_column("Commits", justify="right")
    table.add_column("Sessions", justify="right")

    status_colors = {
        "healthy": "green",
        "stuck": "red",
        "crash-looping": "red",
        "no-commits": "yellow",
        "unknown": "dim",
    }

    for agent in swarm_status.agents:
        color = status_colors.get(agent.status, "white")
        table.add_row(
            agent.agent_id,
            agent.role,
            f"[{color}]{agent.status}[/{color}]",
            agent.current_task or "-",
            agent.last_commit_msg[:40] if agent.last_commit_msg else "-",
            str(agent.total_commits),
            str(agent.session_count),
        )

    console.print(table)
    console.print(f"\nTotal commits: {swarm_status.total_commits} | Active locks: {swarm_status.active_locks}")

    warnings = get_health_warnings(swarm_status)
    for w in warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")


# ── swarm stop ──────────────────────────────────────────────────────────────


@app.command()
def stop(
    agent_id: Optional[str] = typer.Argument(None, help="Stop a specific agent (e.g., 'agent-3')"),
) -> None:
    """Stop all agents (or a specific one)."""
    from swarm.containers import stop_agent, stop_all

    if agent_id:
        aid = agent_id.replace("agent-", "")
        if stop_agent(aid):
            console.print(f"[green]Stopped agent {aid}[/green]")
        else:
            console.print(f"[red]Agent {aid} not found[/red]")
    else:
        count = stop_all()
        console.print(f"[green]Stopped {count} agents[/green]")


# ── swarm logs ──────────────────────────────────────────────────────────────


@app.command()
def logs(
    agent_id: str = typer.Argument("1", help="Agent ID to view logs for"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    all_agents: bool = typer.Option(False, "--all", help="Show interleaved logs from all agents"),
) -> None:
    """View agent logs."""
    logs_dir = Path.cwd() / "agent_logs"
    if not logs_dir.is_dir():
        console.print("[yellow]No agent_logs/ directory found[/yellow]")
        raise typer.Exit(1)

    if all_agents:
        log_files = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    else:
        log_files = sorted(
            logs_dir.glob(f"{agent_id}_*.log"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

    if not log_files:
        console.print(f"[yellow]No logs found for agent {agent_id}[/yellow]")
        raise typer.Exit(1)

    latest = log_files[0]
    console.print(f"[bold]Log: {latest.name}[/bold]\n")
    content = latest.read_text(errors="ignore")
    output_lines = content.splitlines()[-lines:]
    for line in output_lines:
        console.print(line)


# ── swarm cost ──────────────────────────────────────────────────────────────


@app.command()
def cost(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Show cost summary."""
    from swarm.config import load_config
    from swarm.cost import check_cost_limit, compute_cost_summary, scan_agent_logs

    cfg = load_config(Path.cwd(), config)
    logs_dir = Path.cwd() / "agent_logs"

    sessions = scan_agent_logs(logs_dir, cfg.agents.model)
    summary = compute_cost_summary(sessions)

    table = Table(title="Cost Summary")
    table.add_column("Agent", style="bold")
    table.add_column("Cost", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")

    for agent_id, agent_cost in sorted(summary.cost_by_agent.items()):
        agent_sessions = [s for s in sessions if s.agent_id == agent_id]
        inp = sum(s.input_tokens for s in agent_sessions)
        out = sum(s.output_tokens for s in agent_sessions)
        table.add_row(agent_id, f"${agent_cost:.2f}", f"{inp:,}", f"{out:,}")

    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]${summary.total_cost_usd:.2f}[/bold]",
        f"{summary.total_input_tokens:,}",
        f"{summary.total_output_tokens:,}",
    )

    console.print(table)
    console.print(f"\nBudget: ${summary.total_cost_usd:.2f} / ${cfg.limits.max_cost_usd:.2f}")

    if check_cost_limit(summary, cfg.limits.max_cost_usd):
        console.print("[red bold]COST LIMIT EXCEEDED[/red bold]")


# ── swarm history ───────────────────────────────────────────────────────────


@app.command()
def history(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file path"),
    count: int = typer.Option(20, "--count", "-n", help="Number of commits to show"),
) -> None:
    """Show swarm commit history."""
    from swarm.config import load_config

    cfg = load_config(Path.cwd(), config)
    upstream = Path(cfg.git.upstream)

    if not upstream.is_dir():
        console.print("[yellow]Upstream repo not found. Has swarm run been started?[/yellow]")
        raise typer.Exit(1)

    result = subprocess.run(
        [
            "git", "log", "--oneline", "--graph",
            "--author=swarm-agent-",
            f"-{count}",
            cfg.git.branch,
        ],
        cwd=upstream,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        console.print("[yellow]No swarm commits found yet[/yellow]")
        return

    console.print("[bold]Swarm commit history:[/bold]\n")
    console.print(result.stdout)


# ── swarm version ───────────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Show swarm version."""
    console.print(f"swarm-ai {__version__}")


def main() -> None:
    app()
