from __future__ import annotations

import json

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.exceptions import ConfigError
from orchestrator.storage.models import AgentORM, RunORM


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

    def update(self, agent: AgentORM, updates: dict[str, str]) -> AgentORM:
        def parse_jsonish(value: str):
            lowered = value.strip().lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
            if lowered == "null":
                return None
            try:
                if value.strip().isdigit() or (value.strip().startswith("-") and value.strip()[1:].isdigit()):
                    return int(value)
            except Exception:
                pass
            return value

        for key, value in updates.items():
            if key in {"name", "execution_backend", "task_selector_strategy", "push_policy", "autonomy_level"}:
                setattr(agent, key, str(value))
                continue
            if key in {"max_steps"}:
                try:
                    setattr(agent, key, int(value))
                except ValueError as exc:
                    raise ConfigError(f"Invalid integer for {key}: {value}") from exc
                continue
            if key in {"active"}:
                lowered = str(value).strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    setattr(agent, key, True)
                elif lowered in {"false", "0", "no", "n", "off"}:
                    setattr(agent, key, False)
                else:
                    raise ConfigError(f"Invalid boolean for {key}: {value}")
                continue
            if key.startswith("model_settings."):
                inner_key = key.removeprefix("model_settings.")
                payload = json.loads(agent.model_settings_json or "{}")
                payload[inner_key] = parse_jsonish(value)
                agent.model_settings_json = json.dumps(payload)
                continue
            if key.startswith("safety_settings."):
                inner_key = key.removeprefix("safety_settings.")
                payload = json.loads(agent.safety_settings_json or "{}")
                payload[inner_key] = parse_jsonish(value)
                agent.safety_settings_json = json.dumps(payload)
                continue
            if key.startswith("commit_policy."):
                inner_key = key.removeprefix("commit_policy.")
                payload = json.loads(agent.commit_policy_json or "{}")
                payload[inner_key] = parse_jsonish(value)
                agent.commit_policy_json = json.dumps(payload)
                continue
            raise ConfigError(f"Unknown agent config key: {key}")
        self.session.flush()
        return agent

    def delete_full(self, agent: AgentORM) -> None:
        self.session.execute(delete(RunORM).where(RunORM.agent_id == agent.id))
        self.session.delete(agent)
        self.session.flush()
