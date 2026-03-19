from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.storage.models import AgentORM


class AgentService:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        name: str,
        prompt_source_id: int,
        project_repo_id: int,
        execution_backend: str = "multi",
        task_selector_strategy: str = "priority_then_oldest",
        validation_policy: list[dict] | None = None,
        model_settings: dict | None = None,
        safety_settings: dict | None = None,
        push_policy: str = "never",
        autonomy_level: str = "semi-auto",
        max_steps: int = 20,
    ) -> AgentORM:
        item = AgentORM(
            name=name,
            prompt_source_id=prompt_source_id,
            project_repo_id=project_repo_id,
            execution_backend=execution_backend,
            task_selector_strategy=task_selector_strategy,
            validation_policy_json=json.dumps(validation_policy or []),
            model_settings_json=json.dumps(model_settings or {}),
            safety_settings_json=json.dumps(safety_settings or {}),
            commit_policy_json=json.dumps({"message_template": "feat(agent): complete {task_ref} {title}"}),
            push_policy=push_policy,
            autonomy_level=autonomy_level,
            max_steps=max_steps,
            active=True,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list(self) -> list[AgentORM]:
        return list(self.session.scalars(select(AgentORM).order_by(AgentORM.id)).all())

    def get(self, agent_id_or_name: str) -> AgentORM | None:
        stmt = select(AgentORM).where(AgentORM.name == agent_id_or_name)
        item = self.session.scalar(stmt)
        if item:
            return item
        if agent_id_or_name.isdigit():
            return self.session.get(AgentORM, int(agent_id_or_name))
        return None
