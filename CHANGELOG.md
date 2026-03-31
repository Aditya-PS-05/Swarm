# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Initial project scaffolding
- Configuration system (`swarm.toml`)
- Project analyzer (language, task, and test discovery)
- Git sync engine (bare repo, clone, push/pull with conflict resolution)
- File-based task lock manager
- Docker container manager with per-language Dockerfile generation
- Agent prompt generator with role-specific instructions
- Agent monitor with health checks
- Cost tracker with hard limits
- CLI: `swarm init`, `run`, `status`, `stop`, `logs`, `cost`, `history`
