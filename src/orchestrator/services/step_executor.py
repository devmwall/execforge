from __future__ import annotations

from pathlib import Path

from orchestrator.backends.base import ExecutionBackend
from orchestrator.domain.types import BackendContext, StepExecutionResult, TaskStep
from orchestrator.exceptions import BackendError
from orchestrator.storage.models import TaskORM


class StepExecutor:
    def __init__(self, registry: dict[str, ExecutionBackend], backend_priority: list[str]):
        self.registry = registry
        self.backend_priority = backend_priority

    def execute_steps(
        self,
        steps: list[TaskStep],
        task: TaskORM,
        project_path: Path,
        prompt_root: Path,
        context: BackendContext,
    ) -> list[StepExecutionResult]:
        if len(steps) > context.max_steps:
            raise BackendError(f"Task has {len(steps)} steps but agent max_steps is {context.max_steps}")

        results: list[StepExecutionResult] = []
        for step in steps:
            backend = self._select_backend(step)
            backend_result = backend.execute_step(step, task, project_path, prompt_root, context)
            results.append(
                StepExecutionResult(
                    step_id=step.id,
                    step_type=step.type,
                    backend=backend.name,
                    success=backend_result.success,
                    summary=backend_result.summary,
                    stdout=backend_result.stdout,
                    stderr=backend_result.stderr,
                    tool_invocations=backend_result.tool_invocations,
                )
            )
            if not backend_result.success:
                raise BackendError(
                    f"Step '{step.id}' failed using backend '{backend.name}': {backend_result.summary}"
                )
        return results

    def _select_backend(self, step: TaskStep) -> ExecutionBackend:
        candidates = step.tool_preferences or self.backend_priority
        unavailable: list[str] = []
        for backend_name in candidates:
            backend = self.registry.get(backend_name)
            if not backend:
                continue
            if not backend.supports(step):
                continue
            if not backend.is_available():
                unavailable.append(backend_name)
                continue
            return backend
        suffix = f" unavailable={unavailable}" if unavailable else ""
        raise BackendError(
            f"No backend available for step '{step.id}' type='{step.type}' preferences={candidates}{suffix}"
        )
