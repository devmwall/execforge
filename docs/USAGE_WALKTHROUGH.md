# Example Usage Walkthrough

## 1) Initialize local orchestrator state

```bash
execforge init
```

## 2) Add prompt source and sync tasks

```bash
execforge prompt-source add prompts https://github.com/example/prompts.git --branch main --folder-scope tasks
execforge prompt-source sync prompts
```

## 3) Add target project repo

```bash
execforge project add app ~/src/my-app
```

## 4) Add an agent

```bash
execforge agent add app-agent 1 1 --execution-backend multi --enable-codex --enable-claude
```

## 5) Run once

```bash
execforge agent run app-agent
```

Expected behavior:

- Prompt source syncs from git
- Tasks are discovered from Markdown files
- Task steps are parsed in order from YAML/frontmatter
- Each step is routed to a matching backend (for example codex/claude/shell)
- Next task moves to `in_progress`
- Branch is created: `agent/app-agent/<task-id>`
- Backend performs work
- Validation runs
- Commit is created if not in dry-run and repo changed
- Task status becomes `done` or `failed`
- Run record is persisted

## 6) Inspect state

```bash
execforge task list
execforge run list
execforge config show
execforge doctor
```
