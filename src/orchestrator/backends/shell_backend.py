from __future__ import annotations

from pathlib import Path
import shlex

from orchestrator.backends.base import ExecutionBackend
from orchestrator.domain.types import BackendContext, BackendResult, TaskStep
from orchestrator.exceptions import BackendError
from orchestrator.storage.models import TaskORM
from orchestrator.utils.process import run_command


class ShellBackend(ExecutionBackend):
    name = "shell"
    supported_step_types = {"shell", "command"}

    def __init__(self, command_template: str | None = None, allowed_commands: list[str] | None = None):
        self.command_template = command_template
        self.allowed_commands = set(allowed_commands or [])

    def execute_step(
        self,
        step: TaskStep,
        task: TaskORM,
        project_path: Path,
        prompt_root: Path,
        context: BackendContext,
    ) -> BackendResult:
        task_ref = task.external_id or f"task-{task.id}"
        command = step.command
        if not command:
            if not self.command_template:
                raise BackendError(f"Step '{step.id}' requires command and no shell command_template is configured")
            command = self.command_template.format(task_id=task_ref, title=task.title, step_id=step.id)
        parts = shlex.split(command)
        if not parts:
            raise BackendError("Shell backend command_template resolved to empty command")
        if self.allowed_commands and parts[0] not in self.allowed_commands:
            raise BackendError(f"Command '{parts[0]}' is not in allowed command list")

        result = run_command(parts, cwd=project_path, timeout=context.timeout_seconds)
        success = result.code == 0
        return BackendResult(
            success=success,
            summary=f"Shell command exited with code {result.code}",
            stdout=result.stdout,
            stderr=result.stderr,
            tool_invocations=[{"tool": "shell", "step": step.id, "command": command, "exit_code": result.code}],
        )
