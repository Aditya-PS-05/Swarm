# Swarm — Parallel Agent Orchestrator

> Point it at any repo. It spawns parallel Claude agents that build your project autonomously.
> Inspired by: "Building a C compiler with a team of parallel Claudes" — Nicholas Carlini, Anthropic (Feb 2026)
> Generated: 2026-03-31
> Status: Design phase

---

## Principles (from Carlini)

These are non-negotiable design constraints derived from the blog post:

1. **Loop harness**: Agents run in a `while true` loop. When one session ends, the next begins immediately. The agent never waits for human input.
2. **Container isolation**: Each agent runs in its own Docker container. Never on bare metal. Agents can't interfere with each other's filesystem.
3. **Git as the synchronization layer**: A bare git repo is the single source of truth. Each agent clones locally, works, then pushes. Git's own conflict mechanics handle contention.
4. **File-based task locking**: Agents claim tasks by writing lock files to `current_tasks/`. If two agents race for the same lock, `git push` fails for the second one, forcing it to pick something else.
5. **No orchestration agent**: Each agent decides what to work on autonomously. No central coordinator. The agent prompt and test harness provide enough signal.
6. **Test harness designed for LLMs**: Minimal stdout (avoid context pollution), log details to files, pre-compute summaries, support `--fast` mode for quick random sampling.
7. **Time blindness mitigation**: Print incremental progress sparingly. Include default fast-test options. Agents don't know how long they've been running.
8. **CI gating**: New commits must not break existing tests. Pre-push hooks enforce this.
9. **Agent specialization**: Different agents get different roles (feature builder, deduplicator, test writer, code quality, docs).
10. **Oracle comparison**: When tasks aren't parallelizable (one giant build), use a known-good reference to bisect failures across agents.

---

## v0.1 — Weekend MVP

### 1. Project Setup

#### 1.1 Repository & Packaging
- [ ] Rename default branch to `main`
- [ ] Create .gitignore (Python, Docker, logs, .env)
- [ ] Create LICENSE (MIT)
- [ ] Create README.md (project name, one-liner, usage sketch)
- [ ] Create CHANGELOG.md
- [ ] Create pyproject.toml
  - [ ] Name: swarm
  - [ ] Version: 0.1.0
  - [ ] Python >= 3.11
  - [ ] Build system: hatchling
  - [ ] CLI entry point: `swarm = "swarm.cli:main"`
  - [ ] Dependencies: typer, rich, docker (Docker SDK for Python), gitpython, pyyaml, tomli
  - [ ] Dev dependencies: pytest, pytest-asyncio, ruff, mypy

#### 1.2 Directory Structure
- [ ] Create `src/swarm/` package
- [ ] Create `src/swarm/__init__.py` with version
- [ ] Create `src/swarm/__main__.py`
- [ ] Create `src/swarm/cli.py` — typer CLI app
- [ ] Create `src/swarm/config.py` — load/validate swarm.toml
- [ ] Create `src/swarm/analyzer.py` — project analysis (language, tests, tasks)
- [ ] Create `src/swarm/containers.py` — Docker container lifecycle
- [ ] Create `src/swarm/git_sync.py` — bare repo, push/pull/rebase, conflict handling
- [ ] Create `src/swarm/locks.py` — file-based task locking in current_tasks/
- [ ] Create `src/swarm/prompt.py` — agent prompt generation
- [ ] Create `src/swarm/roles.py` — agent role definitions and assignment
- [ ] Create `src/swarm/monitor.py` — live agent status tracking
- [ ] Create `src/swarm/cost.py` — token/cost estimation
- [ ] Create `tests/` directory with `__init__.py` and `conftest.py`
- [ ] Create `.editorconfig`
- [ ] Create `.python-version` (3.12)

#### 1.3 Development Environment
- [ ] Create virtual environment
- [ ] Install in editable mode
- [ ] Verify `swarm` CLI entry point resolves

---

### 2. Configuration System (`swarm.toml`)

The user creates a `swarm.toml` in their project root (or `swarm init` generates one).

#### 2.1 Config Schema
- [ ] Define `swarm.toml` schema
  ```toml
  [project]
  name = "cambrian"
  path = "."

  [agents]
  count = 4
  model = "claude-opus-4-6"
  timeout_minutes = 30          # max session length before restart

  [agents.roles]
  builders = 2                  # feature implementation
  tester = 1                    # test coverage
  reviewer = 1                  # code quality + dedup

  [git]
  upstream = "/tmp/swarm-upstream.git"   # auto-created bare repo
  branch = "main"
  auto_resolve_conflicts = true

  [tests]
  command = "pytest"
  fast_command = "pytest -x --randomly-seed={agent_id} -k 'not slow'"
  gate_push = true              # block push if tests fail

  [tasks]
  source = "TODO.md"            # where to find tasks
  lock_dir = "current_tasks"    # lock file directory
  # source = "github_issues"    # future: pull from GitHub issues

  [limits]
  max_cost_usd = 50.0           # kill all agents if exceeded
  max_sessions = 100            # hard stop after N sessions total
  ```
- [ ] Implement config loader with defaults
- [ ] Validate config on load (missing fields, bad paths)
- [ ] Support `swarm.toml`, `.swarm.toml`, and `--config path` override

#### 2.2 Config CLI
- [ ] `swarm init` — interactive config generator
  - [ ] Detect project language (Python, Rust, Go, JS/TS, C/C++)
  - [ ] Detect test framework (pytest, cargo test, go test, jest, etc.)
  - [ ] Detect task source (TODO.md, TASKS.md, GitHub issues)
  - [ ] Ask for agent count (default: 4)
  - [ ] Ask for model (default: claude-opus-4-6)
  - [ ] Write `swarm.toml`
- [ ] `swarm config show` — print resolved config

---

### 3. Project Analyzer (`analyzer.py`)

Scans the target repo to understand what agents will be working on.

#### 3.1 Language Detection
- [ ] Detect primary language from file extensions
- [ ] Detect package manager (pyproject.toml, Cargo.toml, package.json, go.mod, CMakeLists.txt)
- [ ] Detect test framework from config files

#### 3.2 Task Discovery
- [ ] Parse TODO.md / TASKS.md for unchecked `- [ ]` items
- [ ] Parse inline `TODO:` / `FIXME:` / `HACK:` comments from source files
- [ ] Count total tasks, categorize by section/priority
- [ ] Future: GitHub Issues API integration

#### 3.3 Test Discovery
- [ ] Detect test directory (tests/, test/, spec/, __tests__/)
- [ ] Count test files and approximate test count
- [ ] Verify test command works (dry run)

#### 3.4 Project Summary Output
- [ ] Generate `SWARM_PROJECT_SUMMARY.md` — consumed by agent prompts
  - [ ] Language, framework, package manager
  - [ ] Test command and current pass/fail count
  - [ ] Task list with priorities
  - [ ] Directory structure overview
  - [ ] Key files (README, DESIGN docs, config)

---

### 4. Git Sync Engine (`git_sync.py`)

Follows Carlini's pattern exactly: bare upstream repo + per-agent local clones.

#### 4.1 Upstream Setup
- [ ] Create bare git repo at configured path
- [ ] Push current project state to bare repo
- [ ] Verify bare repo is valid and has commits

#### 4.2 Agent Clone
- [ ] Clone from bare upstream into agent workspace (`/workspace` inside container)
- [ ] Configure git user.name and user.email per agent (e.g., "swarm-agent-1")
- [ ] Set up remote tracking

#### 4.3 Sync Protocol
- [ ] `sync_pull(workspace)` — pull + rebase from upstream
  - [ ] On conflict: attempt auto-resolve (accept theirs for lock files, ours for code, manual for both-modified)
  - [ ] On unresolvable conflict: abort rebase, reset to upstream, re-apply agent's last commit as patch
- [ ] `sync_push(workspace)` — push to upstream
  - [ ] On push failure (another agent pushed): pull --rebase then retry (max 3 attempts)
  - [ ] On repeated failure: log warning, skip this push, continue working
- [ ] `sync_status(workspace)` — commits ahead/behind upstream

#### 4.4 Pre-Push Test Gate
- [ ] Run test command before allowing push
- [ ] If tests fail: reject push, log failure reason
- [ ] Agent prompt instructs Claude to fix failures before retrying push

---

### 5. Task Lock Manager (`locks.py`)

File-based locking exactly as described by Carlini.

#### 5.1 Lock Operations
- [ ] `acquire_lock(task_name, agent_id)` — write `current_tasks/{task_slug}.lock` with agent ID and timestamp
- [ ] `release_lock(task_name, agent_id)` — delete lock file, commit, push
- [ ] `is_locked(task_name)` — check if lock file exists after pull
- [ ] `list_locks()` — return all active locks with agent IDs
- [ ] `my_locks(agent_id)` — locks held by a specific agent

#### 5.2 Stale Lock Handling
- [ ] Detect stale locks (agent hasn't pushed in > N minutes)
- [ ] Auto-release stale locks on next agent sync
- [ ] Log stale lock releases

#### 5.3 Collision Resolution
- [ ] If two agents create the same lock file simultaneously, `git push` fails for the slower one
- [ ] Losing agent deletes its lock, picks a different task
- [ ] This is handled in the agent prompt instructions, not in swarm code (agents resolve it themselves)

---

### 6. Container Manager (`containers.py`)

Each agent runs in its own Docker container.

#### 6.1 Dockerfile Generation
- [ ] Generate `Dockerfile.swarm` based on project language
  - [ ] Python: python:3.12-slim + pip install + claude code CLI
  - [ ] Rust: rust:latest + claude code CLI
  - [ ] Node: node:20-slim + claude code CLI
  - [ ] Go: golang:1.22 + claude code CLI
  - [ ] Generic: ubuntu:24.04 + project deps + claude code CLI
- [ ] Install Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- [ ] Copy agent entrypoint script
- [ ] Build image, tag as `swarm-agent:{project_name}`

#### 6.2 Container Lifecycle
- [ ] `spawn_agent(agent_id, role)` — docker run with:
  - [ ] Volume mount: upstream bare repo at `/upstream`
  - [ ] Environment: `AGENT_ID`, `AGENT_ROLE`, `ANTHROPIC_API_KEY`
  - [ ] Resource limits: `--memory 4g --cpus 2` (configurable)
  - [ ] Network: isolated (no internet by default, matches Carlini's clean-room approach)
  - [ ] Entrypoint: the loop harness script
- [ ] `stop_agent(agent_id)` — graceful stop (SIGTERM, wait, SIGKILL)
- [ ] `stop_all()` — stop all containers
- [ ] `restart_agent(agent_id)` — stop + spawn
- [ ] `list_agents()` — running containers with status

#### 6.3 Agent Entrypoint Script
- [ ] Clone from /upstream to /workspace
- [ ] Run the `while true` loop:
  ```bash
  while true; do
      cd /workspace
      git pull origin main --rebase || git rebase --abort
      
      LOGFILE="/workspace/agent_logs/${AGENT_ID}_$(date +%s).log"
      
      claude --dangerously-skip-permissions \
             -p "$(cat /workspace/SWARM_AGENT_PROMPT.md)" \
             --model "$MODEL" &> "$LOGFILE"
      
      # Push any work
      git add -A
      git commit -m "swarm(${AGENT_ID}): session work" || true
      git pull origin main --rebase && git push origin main || git rebase --abort
  done
  ```
- [ ] Handle container restart gracefully (don't corrupt workspace)

---

### 7. Agent Prompt Generator (`prompt.py`)

Dynamically generates `SWARM_AGENT_PROMPT.md` placed in each agent's workspace. This is the most critical piece — it's the only thing that tells Claude what to do.

#### 7.1 Prompt Structure
- [ ] **Project context**: name, language, what it does (from README/DESIGN)
- [ ] **Your role**: agent ID, assigned role, what you're responsible for
- [ ] **Task selection protocol**:
  1. `git pull` to get latest state
  2. Read `current_tasks/` to see what's locked
  3. Pick highest-priority unlocked task from task source
  4. Create lock file, commit, push
  5. If push fails, pick different task
  6. When done, delete lock, commit, push
- [ ] **Testing protocol**:
  1. Run fast tests (`--fast`) after every change
  2. Run full test suite before pushing
  3. Never push code that breaks existing tests
  4. If you broke something, fix it before doing anything else
- [ ] **Git protocol**:
  1. Commit frequently with descriptive messages
  2. Pull before push, rebase on conflict
  3. If rebase fails, abort and retry
- [ ] **Output hygiene** (Carlini's context pollution rule):
  1. Don't print thousands of lines of test output — pipe to file, grep for errors
  2. Use `--fast` test mode for quick iteration
  3. Log everything to `agent_logs/`
  4. Write ERROR on the same line as the reason so grep finds it
- [ ] **Progress tracking**:
  1. Update PROGRESS.md with what you've done
  2. Note failed approaches so other agents don't repeat them
  3. Keep README current if you change architecture

#### 7.2 Role-Specific Prompt Sections
- [ ] **Builder**: focus on implementing features from the task list. Pick one task, implement it fully with tests, push.
- [ ] **Tester**: focus on test coverage. Read existing code, find untested paths, write tests. Run coverage reports.
- [ ] **Reviewer**: focus on code quality. Find duplicated code, simplify complex functions, ensure consistency. Don't add features.
- [ ] **Documenter**: focus on docs. Keep README, design docs, and inline comments accurate. Don't change functionality.
- [ ] **Fixer**: focus on failing tests and bugs. Run full test suite, pick a failure, fix it. CI-red-to-green.

#### 7.3 Prompt Generation
- [ ] Template engine (simple string formatting, no Jinja needed for v1)
- [ ] Inject project summary from analyzer
- [ ] Inject current task list
- [ ] Inject role-specific instructions
- [ ] Write to workspace as `SWARM_AGENT_PROMPT.md`

---

### 8. Agent Monitor (`monitor.py`)

Track what agents are doing without interfering.

#### 8.1 Status Collection
- [ ] Poll git log for recent commits per agent (by author name)
- [ ] Read `current_tasks/` for active locks
- [ ] Read `agent_logs/` for latest session logs
- [ ] Track session count per agent
- [ ] Track commits per agent

#### 8.2 Cost Tracking (`cost.py`)
- [ ] Parse agent logs for token usage (Claude Code prints this)
- [ ] Estimate cost per agent per session
- [ ] Running total across all agents
- [ ] Alert when approaching `max_cost_usd` limit
- [ ] Kill all agents when limit exceeded

#### 8.3 Health Checks
- [ ] Detect stuck agents (no commits in > N minutes)
- [ ] Detect crash-looping agents (session ends immediately, restarts)
- [ ] Detect agents that keep failing to push (persistent merge conflicts)
- [ ] Log health warnings

---

### 9. CLI (`cli.py`)

#### 9.1 Core Commands
- [ ] `swarm init` — analyze project, generate swarm.toml
- [ ] `swarm run` — start all agents
  - [ ] `--agents N` — override agent count
  - [ ] `--model MODEL` — override model
  - [ ] `--dry-run` — show what would happen without starting
  - [ ] `--detach` — run in background
- [ ] `swarm status` — show agent status table (agent ID, role, current task, last commit, session count)
- [ ] `swarm stop` — graceful shutdown of all agents
- [ ] `swarm stop agent-3` — stop specific agent
- [ ] `swarm logs agent-1` — tail latest log for an agent
- [ ] `swarm logs --all` — interleaved logs from all agents
- [ ] `swarm cost` — show cost summary
- [ ] `swarm history` — show git log filtered by swarm commits

#### 9.2 Output Design
- [ ] Use rich tables for status display
- [ ] Color-code agent roles
- [ ] Show cost in real-time during `swarm status --watch`

---

### 10. Testing

#### 10.1 Unit Tests
- [ ] test_config.py — config loading, validation, defaults
- [ ] test_analyzer.py — language detection, task parsing, test discovery
- [ ] test_git_sync.py — bare repo creation, clone, push/pull, conflict resolution
- [ ] test_locks.py — acquire, release, stale detection, collision
- [ ] test_prompt.py — prompt generation with different roles and project types
- [ ] test_containers.py — Dockerfile generation, container lifecycle (mock Docker)
- [ ] test_cost.py — token parsing, cost calculation, limit enforcement
- [ ] test_monitor.py — status collection, health checks

#### 10.2 Integration Tests
- [ ] Test full workflow: init → run → agents make commits → stop
- [ ] Test with a small sample project (use cambrian as fixture)
- [ ] Test conflict resolution with simulated concurrent pushes
- [ ] Test cost limit kill switch

---

## v0.2 — Smart Orchestrator

### 11. Smart Task Discovery
- [ ] GitHub Issues integration (`--tasks github`)
- [ ] Linear integration (`--tasks linear`)
- [ ] Parse failing test output to auto-create fix tasks
- [ ] Priority scoring: failing tests > TODOs with "critical" > unchecked TODOs > inline TODOs

### 12. Oracle Comparison Mode
- [ ] For monolithic tasks (like compiling a project), implement Carlini's oracle pattern
- [ ] Split build into N file groups
- [ ] Compile some with reference compiler, some with project's compiler
- [ ] Binary search for which files cause failures
- [ ] Assign different file groups to different agents

### 13. Agent Communication
- [ ] Shared `PROGRESS.md` that agents read/write
- [ ] `FAILED_APPROACHES.md` — log what didn't work so other agents avoid it
- [ ] `DECISIONS.md` — architectural decisions agents make, visible to all
- [ ] All communication is file-based, synced via git (no sideband)

### 14. Advanced Conflict Resolution
- [ ] Semantic merge (understand code structure, not just text diff)
- [ ] Auto-revert agent's commit if it breaks CI
- [ ] Quarantine agent that repeatedly breaks things (reassign to reviewer role)

### 15. Live TUI Dashboard
- [ ] Textual-based live dashboard (like Cambrian's TUI)
- [ ] Panel per agent: role, current task, last commit message, session count
- [ ] Git commit stream (live feed of all agent commits)
- [ ] Cost meter with progress bar toward limit
- [ ] Task burndown (total tasks vs completed)
- [ ] Agent health indicators (green/yellow/red)

---

## v0.3 — Production Hardening

### 16. Resume & Recovery
- [ ] `swarm resume` — restart agents from where they left off
- [ ] Persist session state to `.swarm/state.json`
- [ ] Recover from Docker daemon restart
- [ ] Recover from host machine reboot

### 17. Multi-Model Support
- [ ] Different models per role (Opus for architecture, Sonnet for features, Haiku for docs)
- [ ] Model routing in config:
  ```toml
  [agents.models]
  builders = "claude-sonnet-4-6"
  reviewer = "claude-opus-4-6"
  documenter = "claude-haiku-4-5"
  ```

### 18. Podman Support
- [ ] Support Podman as alternative to Docker (rootless containers)
- [ ] Auto-detect Docker vs Podman

### 19. Remote Execution
- [ ] Run agents on remote machines (SSH-based)
- [ ] Run agents on cloud VMs (AWS/GCP spot instances)
- [ ] Agents connect to same upstream bare repo via SSH remote

### 20. Webhooks & Notifications
- [ ] Webhook on: agent stuck, cost limit approaching, all tasks complete
- [ ] Slack notification integration
- [ ] Discord notification integration

---

## v1.0 — Ecosystem

### 21. Agent Marketplace
- [ ] Share successful agent prompts/roles
- [ ] Community-contributed role templates (security auditor, performance optimizer, etc.)

### 22. Language-Specific Adapters
- [ ] Python adapter: pytest integration, coverage gating, ruff linting
- [ ] Rust adapter: cargo test, clippy, cargo fmt
- [ ] Go adapter: go test, go vet, golangci-lint
- [ ] TypeScript adapter: jest/vitest, tsc, eslint
- [ ] C/C++ adapter: cmake, ctest, clang-tidy

### 23. GitHub App
- [ ] `swarm` as a GitHub App
- [ ] Triggered by issue labels ("swarm:build", "swarm:fix")
- [ ] Creates PR when agents complete work
- [ ] Posts status updates as issue comments

### 24. VS Code Extension
- [ ] Start/stop swarm from VS Code
- [ ] Agent status in sidebar
- [ ] Click to view agent logs
- [ ] Cost display in status bar

---

## Architecture Notes

### Container Layout
```
Host:
  /tmp/swarm-upstream.git/     # bare repo (source of truth)
  
Container (per agent):
  /upstream/                   # mounted bare repo (read-write)
  /workspace/                  # agent's local clone
  /workspace/current_tasks/    # lock files
  /workspace/agent_logs/       # per-session logs
  /workspace/SWARM_AGENT_PROMPT.md  # generated prompt
```

### Data Flow
```
swarm init
  → analyzer scans project
  → writes swarm.toml

swarm run
  → creates bare upstream repo
  → builds Docker image
  → spawns N containers
  → each container:
      → clones from /upstream
      → generates SWARM_AGENT_PROMPT.md
      → enters while-true loop:
          → git pull --rebase
          → claude -p SWARM_AGENT_PROMPT.md
          → git push
      → repeats forever until swarm stop
```

### Key Design Decisions

1. **Git as sync, not a message bus.** Agents communicate only through files committed to git. No Redis, no SQLite, no sockets. Git handles ordering and conflicts. This matches Carlini's design.

2. **No orchestration agent.** Each agent is autonomous. The swarm tool handles infrastructure only (containers, git setup). It does not tell agents what to do — the prompt and test harness do that. This avoids single points of failure and matches Carlini's "no orchestrator" approach.

3. **Agents decide what to work on.** Task prioritization happens in the agent prompt via instructions, not in swarm code. The agent reads the task source, checks locks, and picks the next thing. This keeps swarm simple and agents flexible.

4. **Tests gate everything.** Inspired by Carlini's CI pipeline addition: agents must pass tests before pushing. This is the single most important mechanism for maintaining code quality without human review.

5. **Cost limits are hard stops.** When `max_cost_usd` is reached, all agents are killed. No grace period. Better to stop early than to spend money on agents that are stuck.
