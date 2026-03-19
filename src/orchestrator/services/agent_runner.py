from __future__ import annotations

import json
import logging
from pathlib import Path
import time

from sqlalchemy.orm import Session

from orchestrator.backends.factory import build_backend_registry, default_backend_priority
from orchestrator.config import AppConfig, AppPaths
from orchestrator.domain.types import BackendContext
from orchestrator.exceptions import BackendError, OrchestratorError, RepoError
from orchestrator.git.service import GitService
from orchestrator.logging_setup import ContextAdapter
from orchestrator.services.prompt_source_service import PromptSourceService
from orchestrator.services.run_service import RunService
from orchestrator.services.step_executor import StepExecutor
from orchestrator.services.task_service import TaskService
from orchestrator.storage.models import AgentORM, ProjectRepoORM, PromptSourceORM
from orchestrator.validation.pipeline import run_validation_pipeline, validation_results_to_dict


class AgentRunner:
    def __init__(self, session: Session, paths: AppPaths, config: AppConfig, git: GitService):
        self.session = session
        self.paths = paths
        self.config = config
        self.git = git
        self.prompt_service = PromptSourceService(session, paths, git)
        self.task_service = TaskService(session)
        self.run_service = RunService(session)

    def run_once(self, agent: AgentORM, exclude_task_ids: set[int] | None = None) -> dict:
        project = self.session.get(ProjectRepoORM, agent.project_repo_id)
        if not project:
            raise OrchestratorError(f"Project repo not found for agent {agent.name}")

        source = self.session.get(PromptSourceORM, agent.prompt_source_id)
        if not source:
            raise OrchestratorError(f"Prompt source not found for agent {agent.name}")

        self.prompt_service.sync(source)
        discovered = self.task_service.discover_and_upsert(source)

        task = self.task_service.select_next_for_agent(
            agent,
            project_name=project.name,
            exclude_task_ids=exclude_task_ids,
        )
        run = self.run_service.create(agent.id, task.id if task else None)
        logger = ContextAdapter(logging.getLogger("orchestrator.runner"), {
            "run_id": run.id,
            "agent": agent.name,
            "task": task.external_id if task else "-",
        })
        logger.info("starting agent run")

        if not task:
            self.run_service.complete(run, status="noop", summary="No eligible tasks")
            return {"status": "noop", "discovered": discovered, "run_id": run.id}

        try:
            started = time.monotonic()
            self.task_service.mark_status(task, "in_progress")
            self._prepare_repo(agent, project, task)

            safety = json.loads(agent.safety_settings_json or "{}")
            context = BackendContext(
                run_id=run.id,
                timeout_seconds=int(safety.get("timeout_seconds", self.config.default_timeout_seconds)),
                max_steps=agent.max_steps,
                safety_settings=safety,
            )
            parsed_task = self.task_service.parse_raw_task(task)
            if not parsed_task.steps:
                raise BackendError(f"Task '{task.source_path}' has no executable steps")

            backend_registry = build_backend_registry(agent)
            step_executor = StepExecutor(backend_registry, default_backend_priority(agent))
            step_results = step_executor.execute_steps(
                steps=parsed_task.steps,
                task=task,
                project_path=Path(project.local_path),
                prompt_root=Path(source.local_clone_path),
                context=context,
            )
            tool_invocations: list[dict] = []
            for step_result in step_results:
                tool_invocations.extend(step_result.tool_invocations)

            validations = json.loads(agent.validation_policy_json or "[]")
            validation_results = run_validation_pipeline(
                Path(project.local_path),
                validations,
                timeout=int(safety.get("timeout_seconds", self.config.default_timeout_seconds)),
            )
            any_failed = any(not v.success for v in validation_results)
            if any_failed and safety.get("stop_on_validation_failure", True):
                self.task_service.mark_status(task, "failed")
                self.run_service.complete(
                    run,
                    status="failed",
                    summary="Validation failed",
                    tool_invocations=tool_invocations,
                    validation_results=validation_results_to_dict(validation_results),
                )
                return {"status": "failed", "reason": "validation_failed", "run_id": run.id}

            commit_sha = None
            branch_name = self.git.current_branch(Path(project.local_path))
            if not safety.get("dry_run", False):
                template = json.loads(agent.commit_policy_json or "{}").get(
                    "message_template", "feat(agent): complete {task_ref} {title}"
                )
                task_ref = task.external_id or f"task-{task.id}"
                message = template.format(task_ref=task_ref, title=task.title.lower())
                commit_sha = self.git.commit_all(Path(project.local_path), message)

                should_push = agent.push_policy == "on-success" and safety.get("allow_push", self.config.default_allow_push)
                if should_push and commit_sha:
                    self.git.push(Path(project.local_path), branch_name)

            self.task_service.mark_status(task, "done")
            elapsed = time.monotonic() - started
            self.run_service.complete(
                run,
                status="success",
                summary=f"Completed in {elapsed:.1f}s",
                tool_invocations=tool_invocations,
                validation_results=validation_results_to_dict(validation_results),
                commit_sha=commit_sha,
                branch_name=branch_name,
            )
            logger.info("run completed")
            return {"status": "success", "run_id": run.id, "task": task.title, "commit": commit_sha}

        except (OrchestratorError, Exception) as exc:
            self.task_service.mark_status(task, "failed")
            self.run_service.complete(run, status="failed", summary=str(exc))
            logger.exception("run failed")
            return {"status": "failed", "run_id": run.id, "error": str(exc)}

    def run_loop(
        self,
        agent: AgentORM,
        interval_seconds: int = 30,
        max_iterations: int | None = None,
        only_new_prompts: bool = False,
    ) -> None:
        count = 0
        exclude_task_ids: set[int] = set()
        if only_new_prompts:
            existing = self.task_service.list(status=None)
            exclude_task_ids = {t.id for t in existing if t.prompt_source_id == agent.prompt_source_id}
        while True:
            self.run_once(agent, exclude_task_ids=exclude_task_ids)
            count += 1
            if max_iterations and count >= max_iterations:
                return
            time.sleep(interval_seconds)

    def _prepare_repo(self, agent: AgentORM, project: ProjectRepoORM, task) -> None:
        repo_path = Path(project.local_path)
        self.git.ensure_git_repo(repo_path)

        safety = json.loads(agent.safety_settings_json or "{}")
        require_clean = safety.get("require_clean_working_tree", self.config.default_require_clean_tree)
        if require_clean and not self.git.is_clean(repo_path):
            raise RepoError("Project repo working tree is not clean")

        task_ref = task.external_id or f"task-{task.id}"
        branch = self.git.make_agent_branch_name(agent.name, task_ref)
        allow_branch_create = safety.get("allow_branch_create", True)
        self.git.checkout_branch(repo_path, branch, allow_create=allow_branch_create)
