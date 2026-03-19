from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SelectionOutcome:
    code: str
    reason: str
    selected_task_id: str | None = None
    eligible_count: int = 0
    excluded_count: int = 0
    discovered_count: int = 0
    total_tasks_for_source: int = 0
