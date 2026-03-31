"""Tests for swarm.runtime — container runtime detection."""

from __future__ import annotations

from swarm.runtime import Runtime, RuntimeInfo, detect_runtime


class TestDetectRuntime:
    def test_detects_something(self):
        # At least Docker or Podman should be available in the test env
        try:
            info = detect_runtime()
            assert info.runtime in (Runtime.DOCKER, Runtime.PODMAN)
            assert info.command in ("docker", "podman")
            assert info.version != ""
        except RuntimeError:
            pass  # OK if neither is installed in CI

    def test_runtime_info_fields(self):
        info = RuntimeInfo(
            runtime=Runtime.DOCKER,
            command="docker",
            version="24.0.0",
            rootless=False,
        )
        assert info.runtime == Runtime.DOCKER
        assert not info.rootless

    def test_podman_info(self):
        info = RuntimeInfo(
            runtime=Runtime.PODMAN,
            command="podman",
            version="4.8.0",
            rootless=True,
        )
        assert info.rootless is True
