# Execforge

`execforge` is a local CLI that takes tasks from one repo and applies them to another repo.

## How to think about it

Keep this simple mental model:

- **Prompt source**: where tasks come from (a git repo with task files)
- **Project repo**: the codebase that gets changed
- **Agent**: the execution profile that connects the two and runs tasks

That is the whole product loop.

## Install

Choose one:

```bash
# recommended
pipx install agent-orchestrator

# or
pip install agent-orchestrator

# local dev
pip install -e .
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
---

Create project scaffold.
```

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

## Commands by workflow

### Setup

- `execforge init`
- `execforge doctor`

### Prompt sources (task origin)

- `execforge prompt-source add`
- `execforge prompt-source list`
- `execforge prompt-source sync`

### Project repos (code targets)

- `execforge project add`
- `execforge project list`

### Agents (execution profiles)

- `execforge agent add`
- `execforge agent list`
- `execforge agent list --compact`
- `execforge agent update`
- `execforge agent delete`
- `execforge agent run <agent-name-or-id>`
- `execforge agent loop <agent-name-or-id>`

### Task and run inspection

- `execforge task list`
- `execforge task inspect <task-id>`
- `execforge run list`
- `execforge status`
- `execforge start`

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

## License

MIT (see `LICENSE`).
