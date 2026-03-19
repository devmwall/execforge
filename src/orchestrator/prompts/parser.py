from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

import yaml

from orchestrator.domain.types import PromptTask, TaskStep


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_steps(metadata: dict, body: str) -> list[TaskStep]:
    steps: list[TaskStep] = []
    for idx, item in enumerate(list(metadata.get("steps", []) or []), start=1):
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("id") or f"step-{idx}")
        step_type = str(item.get("type") or "llm_summary")
        steps.append(
            TaskStep(
                id=step_id,
                type=step_type,
                tool_preferences=list(item.get("tool_preferences", []) or []),
                prompt_file=item.get("prompt_file"),
                prompt_inline=item.get("prompt_inline"),
                command=item.get("command"),
                metadata={k: v for k, v in item.items() if k not in {"id", "type", "tool_preferences", "prompt_file", "prompt_inline", "command"}},
            )
        )

    if steps:
        return steps

    # Backward-compatible fallback: a single summary step from body.
    if body.strip():
        return [TaskStep(id="default", type="llm_summary", prompt_inline=body.strip())]
    return []


def parse_task_raw(raw: str, rel_path: str, suffix: str) -> PromptTask:
    metadata: dict = {}
    body = raw
    if suffix.lower() == ".md":
        match = FRONTMATTER_RE.match(raw)
        if match:
            metadata = yaml.safe_load(match.group(1)) or {}
            body = match.group(2).strip()
    else:
        metadata = yaml.safe_load(raw) or {}
        body = str(metadata.get("instructions") or metadata.get("description") or "").strip()

    title = metadata.get("title") or Path(rel_path).stem
    steps = _parse_steps(metadata, body)
    task = PromptTask(
        external_id=metadata.get("id"),
        source_path=rel_path,
        title=title,
        description=body,
        priority=metadata.get("priority", "medium"),
        status=metadata.get("status", "todo"),
        labels=list(metadata.get("labels", []) or []),
        target_repo=metadata.get("target_repo"),
        target_paths=list(metadata.get("target_paths", []) or []),
        depends_on=list(metadata.get("depends_on", []) or []),
        acceptance_criteria=list(metadata.get("acceptance_criteria", []) or []),
        steps=steps,
        raw_content=raw,
        last_seen_hash=sha256(raw.encode("utf-8")).hexdigest(),
    )
    return task


def parse_task_file(path: Path, rel_path: str) -> PromptTask:
    raw = path.read_text(encoding="utf-8")
    return parse_task_raw(raw, rel_path=rel_path, suffix=path.suffix)
