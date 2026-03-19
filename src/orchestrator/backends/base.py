from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from orchestrator.domain.types import BackendContext, BackendResult, TaskStep
from orchestrator.storage.models import TaskORM


class ExecutionBackend(ABC):
    name: str
    supported_step_types: set[str]

    def supports(self, step: TaskStep) -> bool:
        return step.type in self.supported_step_types

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def execute_step(
        self,
        step: TaskStep,
        task: TaskORM,
        project_path: Path,
        prompt_root: Path,
        context: BackendContext,
    ) -> BackendResult:
        raise NotImplementedError
