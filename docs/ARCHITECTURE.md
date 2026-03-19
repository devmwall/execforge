# Architecture Overview

This project uses a small layered structure designed for a local-first CLI workflow.

## Layers

1. CLI (`orchestrator.cli`)
   - Typer command definitions
   - Input parsing and output formatting

2. Services (`orchestrator.services`)
   - Core use-case orchestration (add/list/sync/run)
   - Agent lifecycle coordination

3. Integrations
   - Git operations (`orchestrator.git`)
   - Task parsing (`orchestrator.prompts`)
   - Execution backends (`orchestrator.backends`)
   - Step router/executor (`orchestrator.services.step_executor`)
   - Validation pipeline (`orchestrator.validation`)

4. Persistence (`orchestrator.storage`)
   - SQLAlchemy ORM models
   - SQLite session lifecycle

## State model

- Prompt sources are git repositories cloned to app state directory.
- Project repos are local paths that remain external and unmanaged by app config files.
- Tasks are discovered from prompt source files and tracked in SQLite for status/history.
- Runs record each execution attempt with outcome, validations, commit SHA, and logs path.

## Run lifecycle

1) Sync prompt source
2) Discover tasks
3) Select next eligible task
4) Validate repo state and switch/create branch
5) Execute backend
   - Parse ordered task steps
   - Select backend per step from `tool_preferences` and enabled backend registry
   - Fail explicitly when no backend can satisfy a step
6) Run validation steps
7) Commit/push based on policy and safety settings
8) Persist run record and task status
