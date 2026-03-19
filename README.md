# Repo Orchestrator

Production-minded Python CLI for autonomous local repo orchestration.

This tool lets you register prompt/task sources, register local project repos, define configurable agents, and run those agents against tasks from a git-backed prompt repository.

## Why this exists

- Keep automation state outside managed repos
- Make local autonomous workflows reproducible and inspectable
- Support multiple backends instead of hardcoding one provider
- Keep architecture small, practical, and open-source friendly

## Features in v0.1 scaffold

- Prompt Source registry (git URL, local clone path, branch, folder scope, sync strategy)
- Project Repo registry (local git repos allowed for modification)
- Agent definitions (backend, safety settings, validation policy, commit/push policy)
- Task discovery from Markdown + YAML frontmatter
- SQLite state in user app data directory
- Agent run lifecycle with run history and status tracking
- Step-driven multi-backend orchestration
- Built-in backends:
  - `shell`: executes explicit step commands
  - `claude`: external CLI backend (when enabled)
  - `codex`: external CLI backend (when enabled)
  - `opencode`: external CLI backend (when enabled)
  - `mock`: fallback/demo backend
- Validation pipeline (`command`, `file_exists`, `grep`)
- Structured logs with persisted log files

## Install

Use one of these paths. All are supported.

### 1) pipx install (recommended)

```bash
pipx install agent-orchestrator
execforge --help
```

### 2) pip install

```bash
pip install agent-orchestrator
execforge --help
```

### Development install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
execforge --help
```

### Verify install

Primary command: `execforge`

Compatibility aliases: `agent-orchestrator`, `orchestrator`, `agent-controlplane`

## App state location

By default, app state is in the platform user data directory:

- Linux: `~/.local/share/agent-orchestrator/`
- macOS: `~/Library/Application Support/agent-orchestrator/`
- Windows: `%LOCALAPPDATA%\agent-orchestrator\agent-orchestrator\`

Override with:

```bash
export AGENT_ORCHESTRATOR_HOME=~/.agent-orchestrator
```

Legacy override is also supported: `ORCHESTRATOR_HOME`.

Structure:

```text
<orchestrator-home>/
  app.db
  config.toml
  logs/
  prompt-sources/
  runs/
  cache/
  locks/
```

## CLI commands

```text
execforge init

execforge prompt-source add
execforge prompt-source list
execforge prompt-source sync

execforge project add
execforge project list

execforge agent add
execforge agent list
execforge agent run <agent-name-or-id>
execforge agent loop <agent-name-or-id>

execforge task list
execforge task inspect <task-id>

execforge run list
execforge config show
execforge doctor
```

## Quick start

1) Initialize state:

```bash
execforge init
```

2) Add prompt source:

```bash
execforge prompt-source add prompts https://github.com/your-org/prompt-repo.git --branch main --folder-scope tasks
execforge prompt-source sync prompts

# if branch is missing on remote and you want execforge to create/push it
execforge prompt-source sync prompts --bootstrap-missing-branch
```

3) Add project repo:

```bash
execforge project add api ~/src/my-api
```

4) Create an agent:

```bash
execforge agent add demo-agent 1 1 --execution-backend multi --enable-mock
```

5) Run the agent once:

```bash
execforge agent run demo-agent
```

6) Inspect tasks and runs:

```bash
execforge task list
execforge run list
```

## Task file format

Tasks can be Markdown with YAML frontmatter, or pure YAML.

```markdown
---
id: task-001
title: Add health check endpoint
status: todo
priority: high
labels: [backend, api]
steps:
  - id: plan
    type: llm_plan
    tool_preferences: [claude, codex]
    prompt_file: prompts/plan.md
  - id: implement
    type: code_edit
    tool_preferences: [codex, opencode]
    prompt_file: prompts/implement.md
  - id: test
    type: shell
    command: python -m pytest
  - id: summarize
    type: llm_summary
    tool_preferences: [claude]
    prompt_inline: Summarize the changes
---

Implement a /health endpoint in the API service.
```

When a step has `tool_preferences`, the orchestrator tries those backends in order.
If none are enabled and capable, the run fails explicitly.

## Safety and autonomy controls

Safety is stored per agent in `safety_settings_json` and currently supports:

- `dry_run`
- `max_files_changed`
- `max_commits_per_run`
- `require_clean_working_tree`
- `allow_push`
- `allow_branch_create`
- `allowed_commands` (shell backend)
- `timeout_seconds`
- `max_retries`
- `stop_on_validation_failure`
- `approval_mode` (`manual`, `semi-auto`, `full-auto`)

## Validation steps

Validation policy is a list of step objects, for example:

```json
[
  {"type": "command", "name": "tests", "command": "python -m pytest"},
  {"type": "file_exists", "name": "health test", "path": "tests/test_health.py"},
  {"type": "grep", "name": "route exists", "path": "src/api/routes.py", "pattern": "/health"}
]
```

## Project layout

See `src/orchestrator` for package modules. The scaffold is organized into:

- `cli/` - Typer commands
- `storage/` - SQLAlchemy models and DB lifecycle
- `services/` - orchestration use-cases
- `backends/` - backend interface + implementations
- `git/` - focused git operations
- `prompts/` - task parsing
- `validation/` - validation pipeline
- `domain/` - runtime dataclasses

## Roadmap

- Better task targeting and dependency graph resolution
- Task state write-back to prompt repo (optional)
- Richer provider-specific CLI adapters for Claude/Codex/OpenCode
- Parallel agent execution and lock coordination
- Retry policies and approval checkpoints
- Better branch policy enforcement and change limits
- Exportable run artifacts and metrics summaries

## License

MIT (or your preferred open-source license in `LICENSE`).
