"""Tests for swarm.containers — Dockerfile generation, entrypoint, assets."""

from __future__ import annotations

from pathlib import Path

from swarm.containers import (
    DOCKERFILES,
    ContainerSpec,
    generate_dockerfile,
    generate_entrypoint,
    write_docker_assets,
)


class TestDockerfileGeneration:
    def test_python_dockerfile(self):
        df = generate_dockerfile("python")
        assert "python:3.12-slim" in df
        assert "claude-code" in df

    def test_rust_dockerfile(self):
        df = generate_dockerfile("rust")
        assert "rust:latest" in df

    def test_javascript_dockerfile(self):
        df = generate_dockerfile("javascript")
        assert "node:20-slim" in df

    def test_typescript_dockerfile(self):
        df = generate_dockerfile("typescript")
        assert "node:20-slim" in df
        assert "typescript" in df

    def test_go_dockerfile(self):
        df = generate_dockerfile("go")
        assert "golang:1.22" in df

    def test_generic_fallback(self):
        df = generate_dockerfile("unknown-lang")
        assert "ubuntu:24.04" in df

    def test_all_have_entrypoint(self):
        for lang in DOCKERFILES:
            df = generate_dockerfile(lang)
            assert "entrypoint.sh" in df

    def test_all_run_as_non_root(self):
        for lang in DOCKERFILES:
            df = generate_dockerfile(lang)
            assert "USER swarm-agent" in df

    def test_node_installed_with_gpg_verification(self):
        df = generate_dockerfile("python")
        assert "gpg" in df
        assert "nodesource-repo.gpg.key" in df


class TestEntrypoint:
    def test_has_while_loop(self):
        script = generate_entrypoint()
        assert "while true" in script

    def test_has_git_operations(self):
        script = generate_entrypoint()
        assert "git pull" in script
        assert "git push" in script

    def test_has_claude_invocation(self):
        script = generate_entrypoint()
        assert "claude" in script
        assert "SWARM_AGENT_PROMPT.md" in script

    def test_reads_api_key_from_secret_file(self):
        script = generate_entrypoint()
        assert "/run/secrets/api_key" in script
        assert "ANTHROPIC_API_KEY" not in script or "export ANTHROPIC_API_KEY" in script


class TestDockerAssets:
    def test_write_assets(self, tmp_path: Path):
        build_dir = tmp_path / "build"
        dockerfile, entrypoint = write_docker_assets(build_dir, "python")
        assert dockerfile.exists()
        assert entrypoint.exists()
        assert dockerfile.name == "Dockerfile.swarm"
        assert entrypoint.name == "entrypoint.sh"
        # Entrypoint should be executable
        assert entrypoint.stat().st_mode & 0o111


class TestContainerSpec:
    def test_spec_fields(self):
        spec = ContainerSpec(
            agent_id="1",
            role="builder",
            image_name="swarm-agent:test",
            upstream_path="/tmp/upstream.git",
            branch="main",
            model="claude-opus-4-6",
        )
        assert spec.agent_id == "1"
        assert spec.memory_limit == "4g"
        assert spec.cpu_limit == 2.0
