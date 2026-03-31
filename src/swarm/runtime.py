"""Container runtime abstraction — Docker and Podman support.

Auto-detects which container runtime is available and provides
a unified interface for building images and managing containers.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


class Runtime(str, Enum):
    DOCKER = "docker"
    PODMAN = "podman"


@dataclass
class RuntimeInfo:
    runtime: Runtime
    command: str  # "docker" or "podman"
    version: str
    rootless: bool = False


def detect_runtime(prefer: str = "auto") -> RuntimeInfo:
    """Auto-detect available container runtime.

    Priority: prefer > docker > podman
    """
    if prefer != "auto":
        rt = Runtime(prefer)
        info = _check_runtime(rt.value)
        if info:
            return info
        raise RuntimeError(f"Requested runtime '{prefer}' is not available")

    # Try Docker first, then Podman
    for rt_name in ["docker", "podman"]:
        info = _check_runtime(rt_name)
        if info:
            log.info("Detected container runtime: %s %s", info.command, info.version)
            return info

    raise RuntimeError(
        "No container runtime found. Install Docker or Podman.\n"
        "  Docker: https://docs.docker.com/get-docker/\n"
        "  Podman: https://podman.io/getting-started/installation"
    )


def _check_runtime(name: str) -> RuntimeInfo | None:
    """Check if a runtime is available and return its info."""
    if not shutil.which(name):
        return None

    result = subprocess.run(
        [name, "version", "--format", "{{.Client.Version}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Podman uses different format
        result = subprocess.run(
            [name, "--version"], capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None

    version = result.stdout.strip().split()[-1] if result.stdout.strip() else "unknown"
    runtime = Runtime.PODMAN if name == "podman" else Runtime.DOCKER

    # Check if rootless (Podman default, Docker optional)
    rootless = False
    if runtime == Runtime.PODMAN:
        rootless = True  # Podman is rootless by default
    else:
        info_result = subprocess.run(
            [name, "info", "--format", "{{.SecurityOptions}}"],
            capture_output=True, text=True,
        )
        if "rootless" in info_result.stdout:
            rootless = True

    return RuntimeInfo(
        runtime=runtime,
        command=name,
        version=version,
        rootless=rootless,
    )


def build_image(runtime: RuntimeInfo, build_dir: Path, tag: str) -> str:
    """Build a container image using the detected runtime."""
    result = subprocess.run(
        [runtime.command, "build", "-f", "Dockerfile.swarm", "-t", tag, "."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{runtime.command} build failed: {result.stderr[-500:]}"
        )
    log.info("Built image %s with %s", tag, runtime.command)
    return tag


def run_container(
    runtime: RuntimeInfo,
    image: str,
    name: str,
    environment: dict[str, str],
    volumes: dict[str, dict[str, str]],
    user: str = "1000:1000",
    memory: str = "4g",
    cpus: float = 2.0,
) -> str:
    """Run a container and return its ID."""
    cmd = [runtime.command, "run", "-d", "--name", name]

    # User
    cmd.extend(["--user", user])

    # Environment
    for key, val in environment.items():
        cmd.extend(["-e", f"{key}={val}"])

    # Volumes
    for host_path, mount in volumes.items():
        mode = mount.get("mode", "rw")
        bind = mount["bind"]
        cmd.extend(["-v", f"{host_path}:{bind}:{mode}"])

    # Resource limits
    cmd.extend(["--memory", memory])
    cmd.extend(["--cpus", str(cpus)])

    # Security
    cmd.extend(["--security-opt", "no-new-privileges:true"])
    cmd.extend(["--pids-limit", "256"])

    cmd.append(image)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to start container {name}: {result.stderr.strip()}"
        )

    container_id = result.stdout.strip()
    log.info("Started container %s (%s) with %s", name, container_id[:12], runtime.command)
    return container_id


def stop_container(runtime: RuntimeInfo, name: str, timeout: int = 10) -> bool:
    """Stop and remove a container."""
    subprocess.run(
        [runtime.command, "stop", "-t", str(timeout), name],
        capture_output=True, timeout=timeout + 5,
    )
    result = subprocess.run(
        [runtime.command, "rm", "-f", name],
        capture_output=True,
    )
    return result.returncode == 0


def stop_all_containers(runtime: RuntimeInfo, prefix: str = "swarm-agent-") -> int:
    """Stop all containers matching the prefix."""
    result = subprocess.run(
        [runtime.command, "ps", "-a", "--filter", f"name={prefix}",
         "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    names = [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]
    stopped = 0
    for name in names:
        if stop_container(runtime, name):
            stopped += 1
    return stopped


def list_containers(
    runtime: RuntimeInfo, prefix: str = "swarm-agent-"
) -> list[dict[str, str]]:
    """List containers matching the prefix."""
    result = subprocess.run(
        [runtime.command, "ps", "-a", "--filter", f"name={prefix}",
         "--format", "{{.Names}}\t{{.Status}}\t{{.ID}}"],
        capture_output=True, text=True,
    )
    containers = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            containers.append({
                "name": parts[0],
                "status": parts[1],
                "id": parts[2],
            })
    return containers
