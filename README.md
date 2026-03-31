# Swarm

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
pip install swarm
```

## Quick start

```bash
cd your-project
swarm init          # generates swarm.toml
swarm run           # spawns agents
swarm status        # watch progress
swarm stop          # shut down
```

## Requirements

- Python >= 3.11
- Docker
- An Anthropic API key (`ANTHROPIC_API_KEY` env var)

## License

MIT
