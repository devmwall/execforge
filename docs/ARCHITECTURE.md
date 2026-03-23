# Architecture Overview

This is a local CLI with a small, practical architecture.

## Mental model in code

- **Prompt source**: git repo with task files
- **Project repo**: local repo to modify
- **Agent**: links source + project + execution settings

## Main layers

1. `orchestrator.cli`
   - command parsing and user output

2. `orchestrator.services`
   - orchestration use-cases (`init`, `sync`, `run`, `loop`)

3. `orchestrator.backends`
   - interchangeable step executors (`shell`, `claude`, `codex`, `opencode`, `mock`)

4. `orchestrator.git` / `orchestrator.prompts` / `orchestrator.validation`
   - focused integration modules

5. `orchestrator.storage`
   - SQLite models and session lifecycle

## Run flow

Each run follows this sequence:

1) sync prompt source
2) discover tasks
3) select next actionable task
4) prepare git branch
5) execute task steps
6) run validations
7) commit/push by policy
8) persist run result

## State location

State is kept outside project repos in user app data:

- SQLite DB
- config file
- logs
- prompt source clones

This keeps target repos clean and makes runs auditable.

## Related docs

- `README.md` for setup and operator-facing command usage
- `docs/USAGE_WALKTHROUGH.md` for end-to-end execution flow
- `docs/LICENSE.md` for licensing and redistribution notes
