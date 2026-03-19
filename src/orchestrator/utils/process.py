from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


@dataclass(slots=True)
class ProcessResult:
    code: int
    stdout: str
    stderr: str


def run_command(command: list[str], cwd: Path, timeout: int = 900) -> ProcessResult:
    if not command:
        return ProcessResult(code=127, stdout="", stderr="executable not found: <empty command>")

    exec_cmd = list(command)
    resolved = shutil.which(command[0])
    if resolved:
        exec_cmd[0] = resolved

    # Windows package managers often install CLI shims as .cmd/.bat.
    # CreateProcess cannot execute these reliably without going through cmd.exe.
    if os.name == "nt" and resolved and resolved.lower().endswith((".cmd", ".bat")):
        exec_cmd = ["cmd", "/c", resolved, *command[1:]]

    try:
        proc = subprocess.run(
            exec_cmd,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return ProcessResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except FileNotFoundError as exc:
        return ProcessResult(code=127, stdout="", stderr=f"executable not found: {command[0]} ({exc})")
