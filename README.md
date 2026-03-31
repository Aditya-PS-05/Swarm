# Swarm AI

Point it at any repo. It spawns parallel Claude agents that build your project autonomously.

Inspired by [Building a C compiler with a team of parallel Claudes](https://www.anthropic.com/engineering/claude-c-compiler) — Nicholas Carlini, Anthropic (Feb 2026).

## How it works

1. **`swarm init`** — Analyzes your project, detects language/tests/tasks, generates `swarm.toml`
2. **`swarm run`** — Creates a bare git repo, builds Docker images, spawns N agent containers
3. Each agent runs in a `while true` loop: pull, work, test, push
4. Agents claim tasks via file-based locks in `current_tasks/`
5. Git handles synchronization and conflict resolution
6. Tests gate every push — broken code never lands

## Install

```bash
pip install swarm-ai
```

## Quick start

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd your-project
swarm init          # generates swarm.toml
swarm run           # spawns agents
swarm status        # watch progress
swarm stop          # shut down
```

## Commands

| Command | Description |
|---|---|
| `swarm init [path]` | Analyze project, generate `swarm.toml` |
| `swarm run` | Build image, spawn agent containers |
| `swarm run --dry-run` | Show what would happen without starting |
| `swarm status` | Rich table of agent health, tasks, commits |
| `swarm stop` | Graceful shutdown of all agents |
| `swarm stop agent-3` | Stop a specific agent |
| `swarm logs [agent_id]` | Tail agent logs |
| `swarm cost` | Show cost summary with budget tracking |
| `swarm history` | Show swarm commit history |
| `swarm config` | Show resolved configuration |

## Configuration

`swarm init` generates a `swarm.toml`:

```toml
[project]
name = "my-project"
path = "."

[agents]
count = 4
model = "claude-opus-4-6"
timeout_minutes = 30

[agents.roles]
builders = 2       # feature implementation
tester = 1         # test coverage
reviewer = 1       # code quality + dedup

[tests]
command = "pytest"
gate_push = true    # block push if tests fail

[limits]
max_cost_usd = 50.0
max_sessions = 100
```

## Design principles

From [Carlini's blog post](https://www.anthropic.com/engineering/claude-c-compiler):

1. **Loop harness** — Agents run in a `while true` loop, never waiting for human input
2. **Container isolation** — Each agent in its own Docker container
3. **Git as sync** — Bare git repo is the single source of truth
4. **File-based locks** — Agents claim tasks via lock files; git push resolves races
5. **No orchestrator** — Each agent decides what to work on autonomously
6. **Tests gate everything** — Broken code never lands

## Security

- Containers run as non-root with `no-new-privileges`
- API keys mounted as read-only secret files (not in env vars)
- Config validates all string inputs against injection
- Atomic lock file creation prevents race conditions
- Node.js installed via GPG-verified apt (no `curl|bash`)

## Requirements

- Python >= 3.11
- Docker
- An Anthropic API key (`ANTHROPIC_API_KEY` env var)

## License

MIT
