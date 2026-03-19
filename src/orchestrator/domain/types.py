from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskStep:
    id: str
    type: str
    tool_preferences: list[str] = field(default_factory=list)
    prompt_file: str | None = None
    prompt_inline: str | None = None
    command: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromptTask:
    external_id: str | None
    source_path: str
    title: str
    description: str
    priority: str = "medium"
    status: str = "todo"
    labels: list[str] = field(default_factory=list)
    target_repo: str | None = None
    target_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    steps: list[TaskStep] = field(default_factory=list)
    raw_content: str = ""
    last_seen_hash: str = ""


@dataclass(slots=True)
class BackendContext:
    run_id: int
    timeout_seconds: int
    max_steps: int
    safety_settings: dict[str, Any]


@dataclass(slots=True)
class BackendResult:
    success: bool
    summary: str
    stdout: str = ""
    stderr: str = ""
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class StepExecutionResult:
    step_id: str
    step_type: str
    backend: str
    success: bool
    summary: str
    stdout: str = ""
    stderr: str = ""
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ValidationStepResult:
    name: str
    success: bool
    details: str
