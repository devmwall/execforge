from __future__ import annotations

from pathlib import Path
import shlex
import shutil

from orchestrator.backends.base import ExecutionBackend
from orchestrator.domain.types import BackendContext, BackendResult, TaskStep
from orchestrator.exceptions import BackendError
from orchestrator.storage.models import TaskORM
from orchestrator.utils.process import run_command


class LlmCliBackend(ExecutionBackend):
    supported_step_types = {"llm_plan", "code_edit", "llm_summary"}

    def __init__(
        self,
        name: str,
        binary: str,
        args: list[str] | None = None,
        prompt_arg_template: str = "{prompt}",
        requires_binary: bool = True,
        model_arg_name: str | None = None,
    ):
        self.name = name
        self.binary = binary
        self.args = list(args or [])
        self.prompt_arg_template = prompt_arg_template
        self.requires_binary = requires_binary
        self.model_arg_name = model_arg_name

    def execute_step(
        self,
        step: TaskStep,
        task: TaskORM,
        project_path: Path,
        prompt_root: Path,
        context: BackendContext,
    ) -> BackendResult:
        if not self.is_available():
            raise BackendError(f"Backend '{self.name}' unavailable: executable '{self.binary}' not found in PATH")

        prompt = self._resolve_prompt(step, task, prompt_root)
        cmd = [self.binary, *self.args]

        # Optional per-step model override: step.metadata["model"] = "provider/model"
        # Example: model: ollama/llama3.2
        step_model = step.metadata.get("model") if isinstance(step.metadata, dict) else None
        if step_model and self.model_arg_name and not self._has_arg(self.model_arg_name):
            cmd.extend([self.model_arg_name, str(step_model)])

        cmd.append(self.prompt_arg_template.format(prompt=prompt))
        result = run_command(cmd, cwd=project_path, timeout=context.timeout_seconds)
        summary = f"{self.name} exited with code {result.code}"
        if result.code == 127:
            summary = (
                f"{self.name} executable not found. "
                f"Install '{self.binary}', disable this backend, or enable mock fallback for the agent"
            )
        return BackendResult(
            success=result.code == 0,
            summary=summary,
            stdout=result.stdout,
            stderr=result.stderr,
            tool_invocations=[{"tool": self.name, "step": step.id, "command": shlex.join(cmd), "exit_code": result.code}],
        )

    def is_available(self) -> bool:
        if not self.requires_binary:
            return True
        return shutil.which(self.binary) is not None

    def _resolve_prompt(self, step: TaskStep, task: TaskORM, prompt_root: Path) -> str:
        if step.prompt_inline:
            return step.prompt_inline
        if step.prompt_file:
            task_file_path = prompt_root / task.source_path
            candidates = [task_file_path.parent / step.prompt_file, prompt_root / step.prompt_file]
            for candidate in candidates:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
            raise BackendError(f"Prompt file not found for step '{step.id}': {step.prompt_file}")
        return task.description

    def _has_arg(self, flag: str) -> bool:
        return any(arg == flag or arg.startswith(f"{flag}=") for arg in self.args)
