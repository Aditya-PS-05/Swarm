"""Container manager — Docker container lifecycle for swarm agents.

Each agent runs in its own Docker container with:
- A clone of the upstream bare repo
- The while-true loop harness
- Claude Code CLI installed
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ── Dockerfile templates per language ───────────────────────────────────────
# Security: use GPG-verified apt for Node.js, run as non-root user

_NODE_INSTALL = """\
RUN apt-get update && apt-get install -y git curl gnupg && rm -rf /var/lib/apt/lists/* \\
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \\
       | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg \\
    && echo "deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \\
       > /etc/apt/sources.list.d/nodesource.list \\
    && apt-get update && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*"""

_USER_SETUP = """\
RUN useradd -m -s /bin/bash -u 1000 swarm-agent \\
    && mkdir -p /workspace /run/secrets \\
    && chown -R swarm-agent:swarm-agent /workspace
USER swarm-agent"""

DOCKERFILES: dict[str, str] = {
    "python": textwrap.dedent(f"""\
        FROM python:3.12-slim
        {_NODE_INSTALL}
        RUN npm install -g @anthropic-ai/claude-code
        RUN pip install --no-cache-dir pytest ruff
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
    "rust": textwrap.dedent(f"""\
        FROM rust:latest
        {_NODE_INSTALL}
        RUN npm install -g @anthropic-ai/claude-code
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
    "javascript": textwrap.dedent(f"""\
        FROM node:20-slim
        RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
        RUN npm install -g @anthropic-ai/claude-code
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
    "typescript": textwrap.dedent(f"""\
        FROM node:20-slim
        RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
        RUN npm install -g @anthropic-ai/claude-code typescript
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
    "go": textwrap.dedent(f"""\
        FROM golang:1.22
        {_NODE_INSTALL}
        RUN npm install -g @anthropic-ai/claude-code
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
    "generic": textwrap.dedent(f"""\
        FROM ubuntu:24.04
        RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
        {_NODE_INSTALL}
        RUN npm install -g @anthropic-ai/claude-code
        WORKDIR /workspace
        COPY entrypoint.sh /entrypoint.sh
        RUN chmod +x /entrypoint.sh
        {_USER_SETUP}
        ENTRYPOINT ["/entrypoint.sh"]
    """),
}

# ── Entrypoint script (the while-true loop) ────────────────────────────────

ENTRYPOINT_SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -euo pipefail

    UPSTREAM="${UPSTREAM_PATH:-/upstream}"
    BRANCH="${BRANCH:-main}"
    MODEL="${MODEL:-claude-opus-4-6}"
    WORKSPACE="/workspace"

    # Read API key from mounted secret file
    if [ -f /run/secrets/api_key ]; then
        export ANTHROPIC_API_KEY="$(cat /run/secrets/api_key)"
    fi

    # Clone from upstream if workspace is empty
    if [ ! -d "$WORKSPACE/.git" ]; then
        git clone --branch "$BRANCH" "$UPSTREAM" "$WORKSPACE"
        cd "$WORKSPACE"
        git config user.name "swarm-agent-${AGENT_ID}"
        git config user.email "agent-${AGENT_ID}@swarm.local"
    fi

    cd "$WORKSPACE"
    mkdir -p agent_logs current_tasks

    SESSION=0
    while true; do
        SESSION=$((SESSION + 1))
        echo "[agent-${AGENT_ID}] Starting session $SESSION at $(date -Iseconds)"

        # Sync with upstream
        git pull origin "$BRANCH" --rebase || git rebase --abort 2>/dev/null || true

        LOGFILE="agent_logs/${AGENT_ID}_session_${SESSION}_$(date +%s).log"

        # Run Claude Code with the agent prompt
        claude --dangerously-skip-permissions \
               -p "$(cat SWARM_AGENT_PROMPT.md)" \
               --model "$MODEL" \
               --max-turns 50 \
               &> "$LOGFILE" || true

        # Push any work
        git add -A
        git commit -m "swarm(agent-${AGENT_ID}): session ${SESSION} work" || true

        # Pull-rebase-push cycle
        for i in 1 2 3; do
            git pull origin "$BRANCH" --rebase && git push origin "$BRANCH" && break
            echo "[agent-${AGENT_ID}] Push attempt $i failed, retrying..."
            git rebase --abort 2>/dev/null || true
            sleep $((i * 2))
        done

        echo "[agent-${AGENT_ID}] Session $SESSION complete"
    done
""")


@dataclass
class ContainerSpec:
    """Specification for a swarm agent container."""

    agent_id: str
    role: str
    image_name: str
    upstream_path: str
    branch: str
    model: str
    api_key_env: str = "ANTHROPIC_API_KEY"
    memory_limit: str = "4g"
    cpu_limit: float = 2.0


def generate_dockerfile(language: str) -> str:
    """Generate a Dockerfile for the given language."""
    return DOCKERFILES.get(language, DOCKERFILES["generic"])


def generate_entrypoint() -> str:
    """Return the agent entrypoint script."""
    return ENTRYPOINT_SCRIPT


def write_docker_assets(build_dir: Path, language: str) -> tuple[Path, Path]:
    """Write Dockerfile and entrypoint.sh to a build directory."""
    build_dir.mkdir(parents=True, exist_ok=True)

    dockerfile = build_dir / "Dockerfile.swarm"
    dockerfile.write_text(generate_dockerfile(language))

    entrypoint = build_dir / "entrypoint.sh"
    entrypoint.write_text(generate_entrypoint())
    entrypoint.chmod(0o755)

    log.info("Wrote Docker assets to %s", build_dir)
    return dockerfile, entrypoint


def build_image(build_dir: Path, image_name: str) -> str:
    """Build the swarm agent Docker image. Returns the image tag."""
    import docker as docker_sdk

    client = docker_sdk.from_env()
    tag = f"swarm-agent:{image_name}"

    log.info("Building Docker image %s from %s", tag, build_dir)
    client.images.build(
        path=str(build_dir),
        dockerfile="Dockerfile.swarm",
        tag=tag,
        rm=True,
    )
    log.info("Built image %s", tag)
    return tag


def _write_secret_file(api_key: str) -> Path:
    """Write API key to a secure temp file for Docker secret mounting."""
    secret_dir = Path(tempfile.mkdtemp(prefix="swarm-secret-"))
    os.chmod(str(secret_dir), stat.S_IRWXU)  # 0o700 — owner only
    key_file = secret_dir / "api_key"
    key_file.write_text(api_key)
    key_file.chmod(stat.S_IRUSR)  # 0o400 — owner read only
    return key_file


def spawn_agent(spec: ContainerSpec) -> str:
    """Start a container for an agent. Returns the container ID."""
    import docker as docker_sdk

    client = docker_sdk.from_env()
    api_key = os.environ.get(spec.api_key_env, "")
    if not api_key:
        raise RuntimeError(
            f"Environment variable {spec.api_key_env} is not set. "
            "Set it to your Anthropic API key."
        )

    container_name = f"swarm-agent-{spec.agent_id}"

    # Remove existing container with same name if it exists
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
        log.warning("Removed existing container %s", container_name)
    except docker_sdk.errors.NotFound:
        pass
    except docker_sdk.errors.APIError as e:
        log.error("Failed to remove container %s: %s", container_name, e)

    # Mount API key as a read-only secret file instead of env var
    secret_file = _write_secret_file(api_key)

    container = client.containers.run(
        spec.image_name,
        name=container_name,
        detach=True,
        user="1000:1000",
        environment={
            "AGENT_ID": spec.agent_id,
            "AGENT_ROLE": spec.role,
            "MODEL": spec.model,
            "BRANCH": spec.branch,
            "UPSTREAM_PATH": "/upstream",
        },
        volumes={
            spec.upstream_path: {"bind": "/upstream", "mode": "rw"},
            str(secret_file): {"bind": "/run/secrets/api_key", "mode": "ro"},
        },
        mem_limit=spec.memory_limit,
        nano_cpus=int(spec.cpu_limit * 1e9),
        security_opt=["no-new-privileges:true"],
        pids_limit=256,
    )

    container_id: str = container.id  # type: ignore[union-attr]
    log.info(
        "Spawned agent %s (role=%s) as container %s",
        spec.agent_id, spec.role, container.short_id,
    )
    return container_id


def stop_agent(agent_id: str, timeout: int = 10) -> bool:
    """Stop a specific agent container. Returns True if stopped."""
    import docker as docker_sdk

    client = docker_sdk.from_env()
    container_name = f"swarm-agent-{agent_id}"

    try:
        container = client.containers.get(container_name)
        container.stop(timeout=timeout)
        container.remove()
        log.info("Stopped and removed agent %s", agent_id)
        return True
    except docker_sdk.errors.NotFound:
        log.warning("Container %s not found", container_name)
        return False
    except docker_sdk.errors.APIError as e:
        log.error("Failed to stop container %s: %s", container_name, e)
        return False


def stop_all() -> int:
    """Stop all swarm agent containers. Returns count of stopped containers."""
    import docker as docker_sdk

    client = docker_sdk.from_env()
    stopped = 0

    for container in client.containers.list(filters={"name": "swarm-agent-"}):
        container.stop(timeout=10)
        container.remove()
        log.info("Stopped %s", container.name)
        stopped += 1

    return stopped


def list_agents() -> list[dict]:
    """List all running swarm agent containers with status."""
    import docker as docker_sdk

    client = docker_sdk.from_env()
    agents = []

    for container in client.containers.list(all=True, filters={"name": "swarm-agent-"}):
        agents.append({
            "id": container.short_id,
            "name": container.name,
            "status": container.status,
            "agent_id": container.labels.get("agent_id", container.name.replace("swarm-agent-", "")),
        })

    return agents


def restart_agent(agent_id: str, spec: ContainerSpec) -> str:
    """Stop and respawn an agent. Returns new container ID."""
    stop_agent(agent_id)
    return spawn_agent(spec)
