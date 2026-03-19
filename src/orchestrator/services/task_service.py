from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.domain.types import PromptTask
from orchestrator.prompts.parser import parse_task_file, parse_task_raw
from orchestrator.storage.models import AgentORM, PromptSourceORM, TaskORM


PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class TaskService:
    def __init__(self, session: Session):
        self.session = session

    def discover_and_upsert(self, source: PromptSourceORM) -> int:
        root = Path(source.local_clone_path)
        scan_root = root / source.folder_scope if source.folder_scope else root
        files = sorted(
            [*scan_root.rglob("*.md"), *scan_root.rglob("*.yaml"), *scan_root.rglob("*.yml")],
            key=lambda p: str(p),
        )
        count = 0
        for file in files:
            rel = str(file.relative_to(root)).replace("\\", "/")
            parsed = parse_task_file(file, rel)
            self._upsert(source.id, parsed)
            count += 1
        return count

    def _upsert(self, prompt_source_id: int, parsed: PromptTask) -> TaskORM:
        stmt = select(TaskORM).where(
            TaskORM.prompt_source_id == prompt_source_id,
            TaskORM.source_path == parsed.source_path,
        )
        existing = self.session.scalar(stmt)
        if existing:
            existing.title = parsed.title
            existing.description = parsed.description
            existing.priority = parsed.priority
            existing.labels_json = json.dumps(parsed.labels)
            existing.dependencies_json = json.dumps(parsed.depends_on)
            existing.target_paths_json = json.dumps(parsed.target_paths)
            existing.acceptance_criteria_json = json.dumps(parsed.acceptance_criteria)
            existing.target_repo = parsed.target_repo
            existing.raw_content = parsed.raw_content
            existing.last_seen_hash = parsed.last_seen_hash
            existing.external_id = parsed.external_id
            existing.updated_at = datetime.utcnow()
            if existing.status in {"done", "failed", "blocked", "in_progress"}:
                return existing
            existing.status = parsed.status
            return existing

        item = TaskORM(
            prompt_source_id=prompt_source_id,
            external_id=parsed.external_id,
            source_path=parsed.source_path,
            title=parsed.title,
            description=parsed.description,
            labels_json=json.dumps(parsed.labels),
            priority=parsed.priority,
            status=parsed.status,
            dependencies_json=json.dumps(parsed.depends_on),
            target_paths_json=json.dumps(parsed.target_paths),
            target_repo=parsed.target_repo,
            acceptance_criteria_json=json.dumps(parsed.acceptance_criteria),
            raw_content=parsed.raw_content,
            last_seen_hash=parsed.last_seen_hash,
            updated_at=datetime.utcnow(),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list(self, status: str | None = None) -> list[TaskORM]:
        stmt = select(TaskORM)
        if status:
            stmt = stmt.where(TaskORM.status == status)
        tasks = list(self.session.scalars(stmt).all())
        return sorted(tasks, key=lambda t: (PRIORITY_ORDER.get(t.priority, 99), t.updated_at))

    def get(self, task_id: int) -> TaskORM | None:
        return self.session.get(TaskORM, task_id)

    def select_next_for_agent(
        self,
        agent: AgentORM,
        project_name: str | None = None,
        exclude_task_ids: set[int] | None = None,
    ) -> TaskORM | None:
        tasks = self.list(status=None)
        by_external = {t.external_id: t for t in tasks if t.external_id}
        excluded = exclude_task_ids or set()
        for task in tasks:
            if task.prompt_source_id != agent.prompt_source_id:
                continue
            if task.id in excluded:
                continue
            if task.status not in {"todo", "ready"}:
                continue
            if task.target_repo and task.target_repo != "*":
                if not project_name or task.target_repo != project_name:
                    continue
            deps = json.loads(task.dependencies_json or "[]")
            if deps:
                resolved = all(by_external.get(dep) and by_external[dep].status == "done" for dep in deps)
                if not resolved:
                    continue
            return task
        return None

    def mark_status(self, task: TaskORM, status: str) -> None:
        task.status = status
        task.updated_at = datetime.utcnow()

    def parse_raw_task(self, task: TaskORM) -> PromptTask:
        suffix = Path(task.source_path).suffix or ".md"
        return parse_task_raw(task.raw_content, rel_path=task.source_path, suffix=suffix)
