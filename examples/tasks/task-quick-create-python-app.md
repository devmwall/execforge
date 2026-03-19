---
id: quick-001
title: Create a new Python app skeleton
status: todo
priority: high
labels: [quickstart, scaffold]
git:
  base_branch: main
  work_branch: agent/test-agent/quick-001
  push_on_success: false
steps:
  - id: summarize
    type: code_edit
    tool_preferences: [opencode]
    model: ollama/gpt-oss:20b
    prompt_inline: Please create a project of node to test
---

Create a minimal Python project skeleton quickly.
