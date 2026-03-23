# Execforge

`execforge` is a local CLI that syncs task prompts from one repository and applies them to a target project repository.

It is built for a practical operator loop: sync tasks, run an agent, inspect outcomes, and repeat.

## How to think about it

Keep this simple mental model:

- **Prompt source**: where tasks come from (a git repo with task files)
- **Project repo**: the codebase that gets changed
- **Agent**: the execution profile that connects the two and runs tasks

That is the whole product loop.

## Install

Requirements:

- Python 3.11+
- Git
- Optional execution CLIs for LLM backends (`claude`, `codex`, `opencode`)

Choose one:

```bash
# recommended
pipx install execforge

# or
pip install execforge

# npm (requires Python 3.11+ installed)
npm install -g execforge

# local dev
pip install -e .
```

Install with Python virtualenv (local dev):

```bash
# 1) create a virtual environment (Python 3.11+)
python -m venv .venv

# 2) activate it
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# macOS/Linux
source .venv/bin/activate

# 3) upgrade packaging tools (recommended)
python -m pip install --upgrade pip setuptools wheel

# 4) install this project in editable mode
pip install -e .

# 5) verify CLI install
execforge --help
```

Check install:

```bash
execforge --help
```

Aliases also work: `agent-orchestrator`, `orchestrator`, `agent-controlplane`.

## Quick start (workflow-first)

### 1) Initialize

```bash
execforge init
```

The init wizard guides setup for first prompt source, project repo, and agent.

### 2) Connect a task source

```bash
execforge prompt-source add prompts https://github.com/your-org/prompt-repo.git --branch main --folder-scope tasks
execforge prompt-source sync prompts
```

If remote branch is missing and you want Execforge to create/push it:

```bash
execforge prompt-source sync prompts --bootstrap-missing-branch
```

### 3) Connect a project repo

```bash
execforge project add app ~/src/my-app

# workspace mode (parent folder with multiple child repos)
execforge project add mono ~/src --workspace
```

### 4) Create an agent

```bash
execforge agent add app-agent prompts app --execution-backend multi

# ids also work if you prefer
execforge agent add app-agent 1 1 --execution-backend multi
```

### 5) Run the agent

One run:

```bash
execforge agent run app-agent
```

Continuous loop:

```bash
execforge agent loop app-agent
```

Loop defaults to new prompts only. If you want existing eligible tasks too:

```bash
execforge agent loop app-agent --all-eligible-prompts
```

### 6) Inspect results

```bash
execforge task list
execforge run list
execforge status
```

## Daily workflow

```bash
execforge status
execforge prompt-source sync <source-name>
execforge agent run <agent-name>
execforge run list
```

If you want continuous polling:

```bash
execforge agent loop <agent-name>
```

## Backends (Claude/Codex/OpenCode/Shell)

Backends are interchangeable execution options for task steps.

- `shell` for explicit commands
- `claude`, `codex`, `opencode` when those CLIs are installed and enabled
- `mock` fallback backend for local/dev flows

Tasks can express preferences per step, and Execforge routes each step to an available backend.

## Task format

Tasks can be Markdown with YAML frontmatter or pure YAML.

```markdown
---
id: quick-001
title: Create scaffold
status: todo
steps:
  - id: create
    type: shell
    tool_preferences: [shell]
    command: python -m pytest
  - id: summarize
    type: llm_summary
    tool_preferences: [codex, claude, opencode, mock]
    model: ollama/llama3.2
---

Create project scaffold.
```

For OpenCode steps, `model` maps to `--model <provider/model>`.

Optional task-level git overrides:

```yaml
git:
  base_branch: main
  work_branch: agent/custom/quick-001
  push_on_success: false
```

Defaults (when omitted):

- `base_branch`: project repo default branch
- `work_branch`: `agent/<agent-name>/<task-id>`
- `push_on_success`: agent push policy

## Managing configs

### App config

```bash
execforge config                # defaults to config show
execforge config show
execforge config keys
execforge config set log_level DEBUG
execforge config set --set default_timeout_seconds=120 --set default_allow_push=true
execforge config reset default_timeout_seconds
execforge config reset --all
```

Sensitive values are masked in `config show`.

### Agent config

```bash
execforge agent                # defaults to agent list
execforge agent list           # full JSON blocks
execforge agent update test-agent --set max_steps=40 --set push_policy=on-success
execforge agent update test-agent --set safety_settings.allow_push=true
execforge agent delete test-agent --yes
```

## Complete command + config reference (grouped by task)

```text
Setup and health
- execforge init [--interactive/--no-interactive]
  Initialize app home, SQLite DB, and run first-time setup wizard.
- execforge start
  Print the guided first-time command sequence.
- execforge status
  Show setup counts and last run summary.
- execforge doctor
  Check app paths, SQLite access, and git environment.

Prompt sources (task origin repos)
- execforge prompt-source add <name> <repo-url> [branch] [folder_scope] [sync_strategy] [clone_path]
  Register a prompt source definition.
- execforge prompt-source list
  List configured prompt sources.
- execforge prompt-source sync <name-or-id> [--bootstrap-missing-branch]
  Pull/clone source and discover task files.

Project repos (code targets)
- execforge project add <name> <local-path> [default_branch] [allowed_branch_pattern] [--workspace]
  Register either a local git repo, or a parent workspace folder when --workspace is set.
- execforge project list
  List configured project repos.

Agents (execution profiles)
- execforge agent
  Alias for execforge agent list.
- execforge agent add <name> <prompt-source-name-or-id> <project-name-or-id> [options]
  Create an agent linked to one prompt source and one project.
- execforge agent list [--compact]
  List agents (JSON blocks or one-line compact view).
- execforge agent update <agent-name-or-id> --set key=value [--set key=value ...]
  Update agent fields and nested JSON config.
- execforge agent delete <agent-name-or-id> [--yes]
  Delete an agent and its run history.
- execforge agent run <agent-name-or-id> [--verbose] [--debug]
  Execute one run cycle.
- execforge agent loop <agent-name-or-id> [interval_seconds] [max_iterations] [--verbose] [--debug] [--only-new-prompts/--all-eligible-prompts] [--reset-only-new-baseline]
  Run continuously on a polling interval.

Tasks and runs
- execforge task list [status]
  List discovered tasks, optionally filtered by status.
- execforge task inspect <task-id>
  Show parsed task details and steps.
- execforge task set-status <task-id> <status>
  Set status to one of: todo, ready, in_progress, done, failed, blocked.
- execforge task retry <task-id>
  Shortcut that sets task status back to todo.
- execforge run list [limit]
  Show recent run history rows.

App config commands
- execforge config
  Alias for execforge config show.
- execforge config show
  Show current app config and key paths.
- execforge config keys
  List editable app config keys and defaults.
- execforge config set <key> <value>
  Set one config key.
- execforge config set --set key=value [--set key=value ...]
  Set multiple config keys in one command.
- execforge config reset <key> [<key> ...]
  Reset selected keys to defaults.
- execforge config reset --all
  Reset all app config keys to defaults.

Editable app config keys (execforge config set)
- log_level: string, default INFO
- default_timeout_seconds: integer, default 900
- default_require_clean_tree: boolean, default true
- default_allow_push: boolean, default false

Common agent update keys (execforge agent update --set ...)
- Top-level: name, execution_backend, task_selector_strategy, push_policy, autonomy_level, max_steps, active
- Nested JSON maps: model_settings.<key>, safety_settings.<key>, commit_policy.<key>

Workspace mode toggle (agent-level):

- `execforge agent update <agent-name> --set safety_settings.workspace_mode=true`
```

## When nothing runs

If a run ends with noop, Execforge prints the reason and next step.

Common reasons:

- no task files were discovered in the prompt source scope
- all tasks are already in the current only-new baseline
- all tasks are already complete
- tasks exist but none are currently actionable

Useful fixes:

```bash
execforge prompt-source sync <source-name>
execforge task list
execforge agent loop <agent-name> --all-eligible-prompts
execforge agent loop <agent-name> --reset-only-new-baseline
```

`--reset-only-new-baseline` applies to the first loop run, then loop returns to normal only-new behavior.

## Where state is stored

Execforge keeps state outside your project repos.

Default location:

- Linux: `~/.local/share/agent-orchestrator/`
- macOS: `~/Library/Application Support/agent-orchestrator/`
- Windows: `%LOCALAPPDATA%\agent-orchestrator\agent-orchestrator\`

Override:

```bash
export AGENT_ORCHESTRATOR_HOME=~/.agent-orchestrator
```

## More docs

- `docs/USAGE_WALKTHROUGH.md` - practical end-to-end flow
- `docs/ARCHITECTURE.md` - implementation layout
- `docs/LICENSE.md` - license usage and attribution notes

## CI/CD and package publish

This repo includes GitHub Actions pipelines:

- `.github/workflows/ci.yml` - lint, tests, Python package build, `twine check`, and npm package dry-run
- `.github/workflows/publish-testpypi.yml` - manual publish to TestPyPI
- `.github/workflows/publish-pypi.yml` - publish to PyPI and npm on release (and manual dispatch)

Publishing auth:

- `.github/workflows/publish-pypi.yml` uses Trusted Publishing (OIDC) for PyPI and `NPM_TOKEN` for npm.
- `.github/workflows/publish-testpypi.yml` currently uses `TEST_PYPI_API_TOKEN`.

Typical release flow:

```bash
# 1) bump version in pyproject.toml
# 2) commit and tag
git tag v0.1.3
git push origin main --tags

# 3) create/publish a GitHub Release for that tag
#    -> triggers publish-pypi.yml
```

## License

MIT (see `LICENSE`).

For attribution and redistribution guidance, see `docs/LICENSE.md`.
