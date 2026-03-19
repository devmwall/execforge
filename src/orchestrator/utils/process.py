from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(slots=True)
class ProcessResult:
    code: int
    stdout: str
    stderr: str


def run_command(command: list[str], cwd: Path, timeout: int = 900) -> ProcessResult:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return ProcessResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except FileNotFoundError as exc:
        return ProcessResult(code=127, stdout="", stderr=f"executable not found: {command[0]} ({exc})")
