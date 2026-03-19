from __future__ import annotations

from datetime import datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.storage.models import RunORM


class RunService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, agent_id: int, task_id: int | None, logs_path: str | None = None) -> RunORM:
        run = RunORM(agent_id=agent_id, task_id=task_id, started_at=datetime.utcnow(), status="running", logs_path=logs_path)
        self.session.add(run)
        self.session.flush()
        return run

    def complete(
        self,
        run: RunORM,
        status: str,
        summary: str,
        tool_invocations: list[dict] | None = None,
        validation_results: list[dict] | None = None,
        commit_sha: str | None = None,
        branch_name: str | None = None,
    ) -> None:
        run.finished_at = datetime.utcnow()
        run.status = status
        run.summary = summary
        run.tool_invocations_json = json.dumps(tool_invocations or [])
        run.validation_results_json = json.dumps(validation_results or [])
        run.commit_sha = commit_sha
        run.branch_name = branch_name

    def list(self, limit: int = 50) -> list[RunORM]:
        stmt = select(RunORM).order_by(RunORM.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())
