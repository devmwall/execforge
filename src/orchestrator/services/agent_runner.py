from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import re
import time
import traceback

from sqlalchemy.orm import Session

from orchestrator.backends.factory import build_backend_registry, default_backend_priority
from orchestrator.config import AppConfig, AppPaths
from orchestrator.domain.types import BackendContext, TaskGitPolicy
from orchestrator.exceptions import BackendError, OrchestratorError, RepoError
from orchestrator.git.service import GitService
from orchestrator.logging_setup import ContextAdapter
from orchestrator.reporting.console import ConsoleReporter, NullReporter
from orchestrator.reporting.events import LogEvent
from orchestrator.reporting.selection_result import SelectionOutcome
from orchestrator.services.prompt_source_service import PromptSourceService
from orchestrator.services.run_service import RunService
from orchestrator.services.step_executor import StepExecutor
from orchestrator.services.task_service import TaskService
from orchestrator.storage.models import AgentORM, ProjectRepoORM, PromptSourceORM
from orchestrator.utils.process import run_command
from orchestrator.validation.pipeline import run_validation_pipeline, validation_results_to_dict


class AgentRunner:
    def __init__(
        self,
        session: Session,
        paths: AppPaths,
        config: AppConfig,
        git: GitService,
        reporter: ConsoleReporter | None = None,
        log_path: str | None = None,
    ):
        self.session = session
        self.paths = paths
        self.config = config
        self.git = git
        self.prompt_service = PromptSourceService(session, paths, git)
        self.task_service = TaskService(session)
        self.run_service = RunService(session)
        self.reporter = reporter or NullReporter()
        self.log_path = log_path

    def run_once(self, agent: AgentORM, exclude_task_ids: set[int] | None = None) -> dict:
        project = self.session.get(ProjectRepoORM, agent.project_repo_id)
        if not project:
            raise OrchestratorError(f"Project repo not found for agent {agent.name}")

        source = self.session.get(PromptSourceORM, agent.prompt_source_id)
        if not source:
            raise OrchestratorError(f"Prompt source not found for agent {agent.name}")

        run = self.run_service.create(agent.id, None)
        logger = ContextAdapter(logging.getLogger("orchestrator.runner"), {
            "run_id": run.id,
            "agent": agent.name,
            "task": "",
            "base_branch": "",
            "branch": "",
            "step": "",
        })

        self._emit(
            logger,
            LogEvent(
                name="run_started",
                context={
                    "run_id": run.id,
                    "time": datetime.now(),
                    "agent": agent.name,
                    "project": project.name,
                    "prompt_source": source.name,
                },
            ),
        )

        task = None
        parsed_task = None
        task_ref = ""
        base_branch = project.default_branch
        active_branch = ""
        try:
            self._emit(logger, LogEvent(name="prompt_sync_started", phase_index=1, phase_total=6, title="Syncing prompt source"))
            self.prompt_service.sync(source)
            discovered = self.task_service.discover_and_upsert(source)
            self._emit(logger, LogEvent(name="prompt_synced", context={"discovered_tasks": discovered}))

            self._emit(logger, LogEvent(name="repo_validate_started", phase_index=2, phase_total=6, title="Validating project repo"))
            self._refresh_project_repo(project, logger)

            self._emit(logger, LogEvent(name="task_select_started", phase_index=3, phase_total=6, title="Selecting task"))
            eligible = self.task_service.eligible_for_agent(
                agent,
                project_name=project.name,
                exclude_task_ids=exclude_task_ids,
            )
            task = eligible[0] if eligible else None
            run.task_id = task.id if task else None
            task_ref = (task.external_id or f"task-{task.id}") if task else ""
            source_tasks = [t for t in self.task_service.list(status=None) if t.prompt_source_id == source.id]
            eligible_unfiltered = self.task_service.eligible_for_agent(
                agent,
                project_name=project.name,
                exclude_task_ids=None,
            )
            selection = self._build_selection_outcome(
                selected_task_ref=task_ref or None,
                discovered_count=discovered,
                source_tasks=source_tasks,
                eligible_filtered=eligible,
                eligible_unfiltered=eligible_unfiltered,
                excluded_count=len(exclude_task_ids or set()),
                project_name=project.name,
            )
            self._emit(
                logger,
                LogEvent(
                    name="task_selection_completed",
                    context={
                        "code": selection.code,
                        "selected_task_id": selection.selected_task_id,
                        "reason": selection.reason,
                        "next_hint": selection.next_hint,
                        "eligible_count": selection.eligible_count,
                        "excluded_count": selection.excluded_count,
                        "discovered_count": selection.discovered_count,
                    },
                ),
            )
            if not task:
                self.run_service.complete(run, status="noop", summary="No eligible tasks")
                self._emit(
                    logger,
                    LogEvent(
                        name="run_noop",
                        context={
                            "code": selection.code,
                            "reason": selection.reason,
                            "next_hint": selection.next_hint,
                            "project": project.name,
                            "warnings": self.reporter.warnings_in_run,
                        },
                    ),
                )
                return {
                    "status": "noop",
                    "discovered": discovered,
                    "eligible_count": len(eligible),
                    "reason": selection.reason,
                    "run_id": run.id,
                }

            parsed_task = self.task_service.parse_raw_task(task)

            self._emit(logger, LogEvent(name="branch_prepare_started", phase_index=4, phase_total=6, title="Preparing branch"))
            base_branch, active_branch = self._prepare_repo(agent, project, task, parsed_task.git, logger)
            self._emit(logger, LogEvent(name="branch_prepared", context={"base_branch": base_branch, "branch": active_branch}))

            started = time.monotonic()
            self.task_service.mark_status(task, "in_progress")

            if not parsed_task.steps:
                raise BackendError(f"Task '{task.source_path}' has no executable steps")

            safety = json.loads(agent.safety_settings_json or "{}")
            context = BackendContext(
                run_id=run.id,
                timeout_seconds=int(safety.get("timeout_seconds", self.config.default_timeout_seconds)),
                max_steps=agent.max_steps,
                safety_settings=safety,
            )
            commit_after_each_step = bool(safety.get("commit_after_each_step", True))
            task_push_override = parsed_task.git.push_on_success
            should_push = (
                task_push_override
                if task_push_override is not None
                else (agent.push_policy == "on-success" and safety.get("allow_push", self.config.default_allow_push))
            )
            push_reason = (
                "task override" if task_push_override is not None else "agent push_policy + allow_push"
            )
            if self.reporter.mode in {"verbose", "debug"}:
                self._emit(
                    logger,
                    LogEvent(
                        name="warning",
                        message=f"push setting resolved: enabled={should_push} ({push_reason})",
                        context={"branch": active_branch, "task_id": task_ref},
                    ),
                )
            backend_registry = build_backend_registry(agent)
            if self.reporter.mode in {"verbose", "debug"}:
                self._emit(
                    logger,
                    LogEvent(name="warning", message=f"enabled backends: {list(backend_registry.keys())}"),
                )

            self._emit(logger, LogEvent(name="steps_started", phase_index=5, phase_total=6, title="Executing steps"))
            step_executor = StepExecutor(backend_registry, default_backend_priority(agent))
            step_results = []

            tool_invocations: list[dict] = []
            for idx, step in enumerate(parsed_task.steps, start=1):
                step_result = step_executor.execute_step(
                    step=step,
                    task=task,
                    project_path=Path(project.local_path),
                    prompt_root=Path(source.local_clone_path),
                    context=context,
                )
                step_results.append(step_result)
                self._emit(
                    logger,
                    LogEvent(
                        name="step_completed",
                        context={
                            "step_index": idx,
                            "step_total": len(parsed_task.steps),
                            "step": step_result.step_id,
                            "backend": step_result.backend,
                            "symbol": "✓" if step_result.success else "✗",
                        },
                    ),
                )
                tool_invocations.extend(step_result.tool_invocations)

                if not safety.get("dry_run", False) and commit_after_each_step:
                    step_message_template = json.loads(agent.commit_policy_json or "{}").get(
                        "step_message_template", "chore(agent): {task_ref} step {step_id}"
                    )
                    step_message = step_message_template.format(
                        task_ref=task_ref,
                        title=task.title.lower(),
                        step_id=step_result.step_id,
                    )
                    step_commit_sha = self.git.commit_all(Path(project.local_path), step_message)
                    if should_push:
                        self.git.push(Path(project.local_path), active_branch)

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
                self._emit(
                    logger,
                    LogEvent(
                        name="run_completed",
                        context={"status": "failed", "task_id": task_ref, "branch": active_branch},
                    ),
                )
                return {"status": "failed", "reason": "validation_failed", "run_id": run.id}

            commit_sha = None
            if not safety.get("dry_run", False):
                if commit_after_each_step:
                    commit_sha = self.git.commit_all(Path(project.local_path), f"chore(agent): {task_ref} finalize")
                else:
                    template = json.loads(agent.commit_policy_json or "{}").get(
                        "message_template", "feat(agent): complete {task_ref} {title}"
                    )
                    message = template.format(task_ref=task_ref, title=task.title.lower())
                    commit_sha = self.git.commit_all(Path(project.local_path), message)
                if should_push:
                    self.git.push(Path(project.local_path), active_branch)

            self.task_service.mark_status(task, "done")
            elapsed = time.monotonic() - started
            self.run_service.complete(
                run,
                status="success",
                summary=f"Completed in {elapsed:.1f}s",
                tool_invocations=tool_invocations,
                validation_results=validation_results_to_dict(validation_results),
                commit_sha=commit_sha,
                branch_name=active_branch,
            )
            self._emit(
                logger,
                LogEvent(
                    name="run_completed",
                    phase_index=6,
                    phase_total=6,
                    title="Finalizing run",
                    context={
                        "status": "success",
                        "task_id": task_ref,
                        "branch": active_branch,
                        "steps_total": len(step_results),
                        "steps_passed": len([s for s in step_results if s.success]),
                        "warnings": self.reporter.warnings_in_run,
                        "log_path": self.log_path,
                        "push_enabled": should_push,
                    },
                ),
            )
            return {"status": "success", "run_id": run.id, "task": task.title, "commit": commit_sha}

        except (OrchestratorError, Exception) as exc:
            step_id = self._extract_step_id(str(exc))
            if task is not None:
                self.task_service.mark_status(task, "failed")
            self.run_service.complete(run, status="failed", summary=str(exc))
            self._emit(
                logger,
                LogEvent(
                    name="step_failed",
                    level="error",
                    context={
                        "step_index": "?",
                        "step_total": "?",
                        "step": step_id or "unknown",
                        "backend": "runtime",
                        "base_branch": base_branch,
                        "branch": active_branch,
                        "task_id": task_ref,
                        "error": str(exc),
                    },
                ),
            )
            self._emit(
                logger,
                LogEvent(
                    name="run_failed",
                    context={"task_id": task_ref, "branch": active_branch, "reason": str(exc)},
                ),
            )
            self._emit(
                logger,
                LogEvent(
                    name="run_completed",
                    context={
                        "status": "failed",
                        "reason": str(exc),
                        "task_id": task_ref,
                        "branch": active_branch,
                        "warnings": self.reporter.warnings_in_run,
                        "log_path": self.log_path,
                    },
                ),
            )
            logging.getLogger("orchestrator.runner").debug(traceback.format_exc())
            return {
                "status": "failed",
                "run_id": run.id,
                "error": str(exc),
                "task_id": task_ref,
                "base_branch": base_branch,
                "active_branch": active_branch,
                "step_id": step_id,
            }

    def run_loop(
        self,
        agent: AgentORM,
        interval_seconds: int = 30,
        max_iterations: int | None = None,
        only_new_prompts: bool = True,
        reset_only_new_baseline: bool = False,
    ) -> None:
        count = 0
        project = self.session.get(ProjectRepoORM, agent.project_repo_id)
        source = self.session.get(PromptSourceORM, agent.prompt_source_id)
        safety = json.loads(agent.safety_settings_json or "{}")
        exclude_task_ids: set[int] = set()
        initial_excluded = 0
        reset_applied = False
        if only_new_prompts:
            if reset_only_new_baseline:
                exclude_task_ids = set()
            else:
                existing = self.task_service.list(status=None)
                exclude_task_ids = {t.id for t in existing if t.prompt_source_id == agent.prompt_source_id}
                initial_excluded = len(exclude_task_ids)
        self._emit(
            ContextAdapter(logging.getLogger("orchestrator.runner"), {"run_id": "", "agent": agent.name}),
            LogEvent(
                name="loop_started",
                context={
                    "time": datetime.now(),
                    "agent": agent.name,
                    "project": project.name if project else "(missing)",
                    "prompt_source": source.name if source else "(missing)",
                    "interval_seconds": interval_seconds,
                    "only_new_prompts": only_new_prompts,
                    "reset_only_new_baseline": reset_only_new_baseline,
                    "initial_excluded": initial_excluded,
                    "allow_dirty_worktree": not safety.get(
                        "require_clean_working_tree", self.config.default_require_clean_tree
                    ),
                    "branch_strategy": "agent/<agent-name>/<task-id>",
                },
            ),
        )
        while True:
            self.run_once(agent, exclude_task_ids=exclude_task_ids)
            count += 1

            # Reset baseline once, then continue in only-new mode from that point forward.
            if only_new_prompts and reset_only_new_baseline and not reset_applied:
                current = self.task_service.list(status=None)
                exclude_task_ids = {t.id for t in current if t.prompt_source_id == agent.prompt_source_id}
                reset_applied = True
                self._emit(
                    ContextAdapter(logging.getLogger("orchestrator.runner"), {"run_id": "", "agent": agent.name}),
                    LogEvent(
                        name="warning",
                        message=(
                            "reset-only-new-baseline applied for first run; "
                            f"continuing with only-new mode and excluded_tasks={len(exclude_task_ids)}"
                        ),
                    ),
                )

            if max_iterations and count >= max_iterations:
                return
            self._emit(
                ContextAdapter(logging.getLogger("orchestrator.runner"), {"run_id": "", "agent": agent.name}),
                LogEvent(
                    name="loop_waiting",
                    context={
                        "interval_seconds": interval_seconds,
                        "next_run_at": datetime.now() + timedelta(seconds=interval_seconds),
                    },
                ),
            )
            time.sleep(interval_seconds)

    def _prepare_repo(
        self,
        agent: AgentORM,
        project: ProjectRepoORM,
        task,
        task_git: TaskGitPolicy,
        logger: ContextAdapter,
    ) -> tuple[str, str]:
        repo_path = Path(project.local_path)
        self.git.ensure_git_repo(repo_path)

        safety = json.loads(agent.safety_settings_json or "{}")
        require_clean = safety.get("require_clean_working_tree", self.config.default_require_clean_tree)
        is_clean = self.git.is_clean(repo_path)
        has_commits = self.git.has_commits(repo_path)
        if require_clean and not is_clean:
            if not has_commits:
                self._emit(logger, LogEvent(name="warning", message="working tree dirty but no commits yet; allowing bootstrap"))
            else:
                status = run_command(["git", "status", "--short"], cwd=repo_path, timeout=self.config.default_timeout_seconds)
                details = status.stdout.strip().splitlines()
                preview = "; ".join(details[:8]) if details else "(unable to list changes)"
                raise RepoError(f"Project repo working tree is not clean: {preview}")
        if not require_clean and not is_clean:
            self._emit(logger, LogEvent(name="warning", message="working tree dirty but allowed by safety settings"))

        base_branch = task_git.base_branch or project.default_branch
        task_ref = task.external_id or f"task-{task.id}"
        work_branch = task_git.work_branch or self.git.make_agent_branch_name(agent.name, task_ref)

        # If dirty worktrees are allowed and we are already on the intended task branch,
        # keep working there instead of forcing a base checkout that would fail.
        if not require_clean and not is_clean:
            try:
                current = self.git.current_branch(repo_path)
            except RepoError:
                current = ""
            if current == work_branch:
                self._emit(
                    logger,
                    LogEvent(
                        name="warning",
                        message=(
                            "continuing on existing dirty task branch; "
                            "skipping base branch checkout/pull for this run"
                        ),
                        context={"branch": work_branch, "base_branch": base_branch, "task_id": task_ref},
                    ),
                )
                return base_branch, work_branch

            # If switching branches with dirty state, checkpoint current branch first.
            if current and current != "HEAD":
                checkpoint_message = (
                    f"chore(agent): checkpoint before switching to {work_branch} for {task_ref}"
                )
                checkpoint_sha = self.git.commit_all(repo_path, checkpoint_message)
                if checkpoint_sha:
                    self._emit(
                        logger,
                        LogEvent(
                            name="warning",
                            message=(
                                "dirty working tree checkpointed on current branch before branch switch; "
                                f"branch={current} commit={checkpoint_sha[:8]}"
                            ),
                            context={"branch": current, "task_id": task_ref},
                        ),
                    )

        self.git.checkout_or_create_tracking_branch(repo_path, base_branch, create_and_push_if_missing=False)
        self.git.pull(repo_path, strategy="ff-only", branch=base_branch, bootstrap_missing_branch=False)
        allow_branch_create = safety.get("allow_branch_create", True)
        self.git.checkout_or_create_branch(repo_path, work_branch, start_point=base_branch, allow_create=allow_branch_create)
        return base_branch, work_branch

    def _refresh_project_repo(self, project: ProjectRepoORM, logger: ContextAdapter) -> None:
        repo_path = Path(project.local_path)
        self.git.ensure_git_repo(repo_path)
        try:
            current = self.git.current_branch(repo_path)
        except RepoError:
            current = "(unborn)"
        self._emit(logger, LogEvent(name="repo_validated", context={"current_branch": current}))

    def _extract_step_id(self, error_message: str) -> str:
        match = re.search(r"Step '([^']+)'", error_message)
        if match:
            return match.group(1)
        return ""

    def _build_selection_outcome(
        self,
        selected_task_ref: str | None,
        discovered_count: int,
        source_tasks: list,
        eligible_filtered: list,
        eligible_unfiltered: list,
        excluded_count: int,
        project_name: str,
    ) -> SelectionOutcome:
        status_counts: dict[str, int] = {}
        for task in source_tasks:
            status = getattr(task, "status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        if selected_task_ref:
            return SelectionOutcome(
                code="selected",
                reason="task selected for execution",
                next_hint=None,
                selected_task_id=selected_task_ref,
                eligible_count=len(eligible_filtered),
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        if discovered_count == 0 and len(source_tasks) == 0:
            return SelectionOutcome(
                code="no_tasks_discovered",
                reason="prompt sync succeeded but no task files were found",
                next_hint="add task files to your prompt source folder, then run: execforge prompt-source sync <source-name>",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=0,
            )
        if len(eligible_unfiltered) > 0 and len(eligible_filtered) == 0:
            return SelectionOutcome(
                code="baseline_filtered",
                reason="all discovered tasks are already part of the current baseline",
                next_hint="run with --all-eligible-prompts or --reset-only-new-baseline",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        if source_tasks and status_counts.get("failed", 0) == len(source_tasks):
            return SelectionOutcome(
                code="all_failed",
                reason="all discovered tasks are currently failed",
                next_hint="retry one task with: execforge task retry <task-id>",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        if source_tasks and status_counts.get("blocked", 0) == len(source_tasks):
            return SelectionOutcome(
                code="all_blocked",
                reason="all discovered tasks are blocked",
                next_hint="inspect dependencies with: execforge task inspect <task-id>",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        if source_tasks and all(getattr(t, "status", "") == "done" for t in source_tasks):
            return SelectionOutcome(
                code="all_completed",
                reason="all discovered tasks are already complete",
                next_hint="add new todo tasks in the prompt source and sync again",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        if source_tasks and (status_counts.get("todo", 0) + status_counts.get("ready", 0)) > 0 and len(eligible_unfiltered) == 0:
            return SelectionOutcome(
                code="tasks_not_actionable",
                reason=(
                    "tasks are present but none are actionable for this agent "
                    f"(check target_repo and dependency rules for project '{project_name}')"
                ),
                next_hint="inspect a task with: execforge task inspect <task-id>",
                eligible_count=0,
                excluded_count=excluded_count,
                discovered_count=discovered_count,
                total_tasks_for_source=len(source_tasks),
            )
        return SelectionOutcome(
            code="no_eligible_tasks",
            reason="no eligible task matched current execution rules",
            next_hint="inspect tasks with: execforge task list and check dependencies/status",
            eligible_count=0,
            excluded_count=excluded_count,
            discovered_count=discovered_count,
            total_tasks_for_source=len(source_tasks),
        )

    def _emit(self, logger: ContextAdapter, event: LogEvent) -> None:
        self.reporter.render(event)
        logging.getLogger("orchestrator.runner").debug("event=%s", json.dumps(event.to_dict(), default=str))
