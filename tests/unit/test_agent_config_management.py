from __future__ import annotations

from pathlib import Path

from orchestrator.services.agent_service import AgentService
from orchestrator.storage.db import init_db, make_engine, session_scope
from orchestrator.storage.models import AgentORM, ProjectRepoORM, PromptSourceORM, RunORM


def _engine(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine = make_engine(str(db_file))
    init_db(engine)
    return engine


def test_agent_update_and_delete_full(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with session_scope(engine) as session:
        source = PromptSourceORM(
            name="ps",
            repo_url="https://example.com/repo.git",
            local_clone_path=str(tmp_path / "ps"),
            branch="main",
            folder_scope=None,
            sync_strategy="ff-only",
            active=True,
        )
        project = ProjectRepoORM(
            name="proj",
            local_path=str(tmp_path / "proj"),
            default_branch="main",
            allowed_branch_pattern="agent/*",
            active=True,
        )
        session.add(source)
        session.add(project)
        session.flush()

        svc = AgentService(session)
        agent = svc.add(
            name="agent-a",
            prompt_source_id=source.id,
            project_repo_id=project.id,
            execution_backend="multi",
        )
        session.add(RunORM(agent_id=agent.id, task_id=None, status="success", summary="ok"))
        session.flush()

        updated = svc.update(
            agent,
            {
                "max_steps": "55",
                "push_policy": "on-success",
                "safety_settings.allow_push": "true",
            },
        )
        assert updated.max_steps == 55
        assert updated.push_policy == "on-success"
        assert "allow_push" in updated.safety_settings_json

        svc.delete_full(agent)

    with session_scope(engine) as session:
        remaining_agent = session.query(AgentORM).filter(AgentORM.name == "agent-a").first()
        assert remaining_agent is None
        remaining_runs = session.query(RunORM).all()
        assert remaining_runs == []
