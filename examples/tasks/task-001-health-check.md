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
    prompt_file: prompts/plan-health.md
  - id: implement
    type: code_edit
    tool_preferences: [codex, opencode]
    prompt_file: prompts/implement-health.md
  - id: test
    type: shell
    command: python -m pytest
  - id: summarize
    type: llm_summary
    tool_preferences: [claude]
    prompt_inline: Summarize health endpoint changes.
---

Implement a `/health` endpoint in the API service.
Add tests for the new route and keep existing routes unchanged.
