from __future__ import annotations

from pathlib import Path

from orchestrator.backends.base import ExecutionBackend
from orchestrator.domain.types import BackendContext, BackendResult, TaskStep
from orchestrator.storage.models import TaskORM


class MockBackend(ExecutionBackend):
    name = "mock"
    supported_step_types = {"llm_plan", "llm_summary", "code_edit", "shell"}

    def execute_step(
        self,
        step: TaskStep,
        task: TaskORM,
        project_path: Path,
        prompt_root: Path,
        context: BackendContext,
    ) -> BackendResult:
        marker = project_path / ".orchestrator"
        marker.mkdir(parents=True, exist_ok=True)
        task_ref = task.external_id or f"task-{task.id}"
        out_file = marker / f"{task_ref}-{step.id}.txt"
        out_file.write_text(
            f"Completed by mock backend for {task_ref}:{step.id} ({step.type})\n\n{task.description}\n",
            encoding="utf-8",
        )
        return BackendResult(
            success=True,
            summary=f"Mock backend completed step {step.id}",
            tool_invocations=[{"tool": "mock_backend", "step": step.id, "output": str(out_file)}],
        )
