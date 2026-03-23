# Usage Walkthrough

This walkthrough follows the normal operator flow.

Requirements:

- Python 3.11+
- Git
- Execforge installed and available on PATH (`execforge --help`)

## 1) Initialize

```bash
execforge init
```

`init` is interactive and helps you add first resources.

## 2) Add a prompt source (task origin)

```bash
execforge prompt-source add prompts https://github.com/example/prompts.git --branch main --folder-scope tasks
execforge prompt-source sync prompts
```

If the branch does not exist remotely and you want Execforge to create it:

```bash
execforge prompt-source sync prompts --bootstrap-missing-branch
```

## 3) Add a project repo (code target)

```bash
execforge project add app ~/src/my-app
```

## 4) Create an agent (execution profile)

```bash
execforge agent add app-agent prompts app --execution-backend multi
```

## 5) Run

Single run:

```bash
execforge agent run app-agent
```

Continuous loop:

```bash
execforge agent loop app-agent
```

Use these loop flags when needed:

- include backlog: `--all-eligible-prompts`
- reset only-new baseline once: `--reset-only-new-baseline`

## 6) Inspect output and state

```bash
execforge task list
execforge task inspect 1
execforge run list
execforge agent list
execforge agent list --compact
execforge config show
execforge status
```

If a run is noop, use:

```bash
execforge task list
execforge prompt-source sync prompts
execforge agent loop app-agent --all-eligible-prompts
```

## What should happen on a successful task

- prompt source is synced
- tasks are discovered
- one eligible task is selected
- task branch is prepared (`agent/<agent>/<task-id>` by default)
- steps run via available backends
- validations run
- changes are committed (unless dry run)
- run history is recorded

## Related docs

- `README.md` for install, command reference, and release workflow
- `docs/ARCHITECTURE.md` for implementation layout
- `docs/LICENSE.md` for license usage and attribution
