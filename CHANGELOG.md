# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-20

### Added

- CLI tool `claude-stats` built with [Typer](https://typer.tiangolo.com/) and
  [Rich](https://rich.readthedocs.io/)
- `summary` command: cost breakdown by model with daily trend (last 14 days)
- `projects` command: cost breakdown by project (top N, bar chart)
- `sessions` command: cost breakdown by session (top N)
- `cache` command: cache savings analysis (cache read/write token details)
- `prompt` command: per-prompt cost ranking (top N)
- Shared CLI options for all commands:
  `--days`/`-d`, `--since`, `--until`, `--project`/`-p`,
  `--top`/`-n`, `--dir`, `--pricing-file`
- `--version`/`-v` flag to print the installed version and exit
- Bundled `pricing.yml` (USD per 1M tokens for Sonnet, Opus, Haiku);
  fully swappable via `--pricing-file`
- Windows path auto-detection: uses `%APPDATA%\Claude\projects` when
  `APPDATA` is set, falls back to `~/.claude/projects`
- 30 pytest test cases covering pricing, cost calculation, formatting,
  record loading, and platform path resolution
