from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re
import shlex

from orchestrator.domain.types import ValidationStepResult
from orchestrator.utils.process import run_command


def run_validation_pipeline(project_path: Path, steps: list[dict], timeout: int = 900) -> list[ValidationStepResult]:
    results: list[ValidationStepResult] = []
    for idx, step in enumerate(steps):
        step_type = step.get("type")
        name = step.get("name") or f"step-{idx + 1}"

        if step_type == "command":
            command = step.get("command", "")
            parts = shlex.split(command)
            if not parts:
                results.append(ValidationStepResult(name=name, success=False, details="empty command"))
                continue
            outcome = run_command(parts, cwd=project_path, timeout=timeout)
            details = outcome.stdout.strip() or outcome.stderr.strip()
            results.append(ValidationStepResult(name=name, success=outcome.code == 0, details=details[:500]))
            continue

        if step_type == "file_exists":
            rel = step.get("path", "")
            exists = (project_path / rel).exists()
            results.append(ValidationStepResult(name=name, success=exists, details=f"exists={exists} path={rel}"))
            continue

        if step_type == "grep":
            rel = step.get("path", "")
            pattern = step.get("pattern", "")
            target = project_path / rel
            if not target.exists():
                results.append(ValidationStepResult(name=name, success=False, details=f"missing file {rel}"))
                continue
            content = target.read_text(encoding="utf-8")
            matched = re.search(pattern, content, re.MULTILINE) is not None
            results.append(ValidationStepResult(name=name, success=matched, details=f"pattern={pattern} matched={matched}"))
            continue

        results.append(ValidationStepResult(name=name, success=False, details=f"unknown type={step_type}"))
    return results


def validation_results_to_dict(results: list[ValidationStepResult]) -> list[dict]:
    return [asdict(r) for r in results]
