from __future__ import annotations

import json
from pathlib import Path
import shutil

import typer
from typer import Context

from orchestrator.config import (
    AppConfig,
    ensure_app_dirs,
    get_app_paths,
    load_config,
    save_config,
)
from orchestrator.config import (
    config_to_display_dict,
    get_config_schema,
    reset_config_values,
    update_config_values,
)
from orchestrator.exceptions import ConfigError, OrchestratorError
from orchestrator.git.service import GitService
from orchestrator.logging_setup import configure_logging
from orchestrator.reporting.console import ConsoleReporter
from orchestrator.services.agent_runner import AgentRunner
from orchestrator.services.agent_service import AgentService
from orchestrator.services.project_service import ProjectService
from orchestrator.services.prompt_source_service import PromptSourceService
from orchestrator.services.run_service import RunService
from orchestrator.services.task_service import TaskService
from orchestrator.storage.db import init_db, make_engine, session_scope
from orchestrator.storage.models import ProjectRepoORM, PromptSourceORM


app = typer.Typer(
    help=(
        "ExecForge runs tasks from a prompt source repo against a project repo.\n\n"
        "Typical flow:\n"
        "  1) execforge init\n"
        "  2) execforge prompt-source add ... && execforge prompt-source sync ...\n"
        "  3) execforge project add ...\n"
        "  4) execforge agent add ...\n"
        "  5) execforge agent run <agent> or execforge agent loop <agent>\n\n"
        "Examples:\n"
        "  execforge agent list\n"
        "  execforge agent run ollama-test\n"
        "  execforge agent loop ollama-test --all-eligible-prompts\n"
        "  execforge run list\n"
        "  execforge status"
    )
)
prompt_source_app = typer.Typer(help="Manage prompt sources")
project_app = typer.Typer(help="Manage project repositories")
agent_app = typer.Typer(
    help=(
        "Manage and run agents.\n\n"
        "Examples:\n"
        "  execforge agent\n"
        "  execforge agent list --compact\n"
        "  execforge agent run ollama-test\n"
        "  execforge agent loop ollama-test --all-eligible-prompts"
    )
)
task_app = typer.Typer(help="Inspect discovered tasks")
run_app = typer.Typer(
    help=(
        "Inspect execution runs (history and status), not agent execution.\n\n"
        "Examples:\n"
        "  execforge run list\n"
        "  execforge run list --limit 100\n"
        "  execforge agent run ollama-test"
    )
)
config_app = typer.Typer(help="Configuration commands")

app.add_typer(prompt_source_app, name="prompt-source")
app.add_typer(project_app, name="project")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.add_typer(run_app, name="run")
app.add_typer(config_app, name="config")


@agent_app.callback(invoke_without_command=True)
def agent_root(ctx: Context):
    """Default to listing agents when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        agent_list()


@config_app.callback(invoke_without_command=True)
def config_root(ctx: Context):
    """Default to showing config when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        config_show()


def _runtime(console_debug: bool = False, force_debug_logging: bool = False):
    paths = get_app_paths()
    ensure_app_dirs(paths)
    config = load_config(paths)
    level = "DEBUG" if force_debug_logging else config.log_level
    log_path = configure_logging(paths.logs_dir, level, console_debug=console_debug)
    engine = make_engine(str(paths.db_file))
    init_db(engine)
    git = GitService(timeout_seconds=config.default_timeout_seconds)
    return paths, config, engine, git, log_path


def _detect_backend_binaries() -> dict[str, bool]:
    return {
        "claude": shutil.which("claude") is not None,
        "codex": shutil.which("codex") is not None,
        "opencode": shutil.which("opencode") is not None,
    }


def _wizard_model_settings(
    profile: str, command_template: str, detected: dict[str, bool]
) -> dict[str, object]:
    if profile == "mock":
        return {
            "backend_priority": ["mock", "shell"],
            "backends": {
                "shell": {"enabled": True},
                "claude": {"enabled": False},
                "codex": {"enabled": False},
                "opencode": {"enabled": False},
                "mock": {"enabled": True},
            },
        }

    if profile == "shell":
        model_settings: dict[str, object] = {
            "backend_priority": ["shell", "mock"],
            "backends": {
                "shell": {"enabled": True},
                "claude": {"enabled": False},
                "codex": {"enabled": False},
                "opencode": {"enabled": False},
                "mock": {"enabled": True},
            },
        }
        if command_template:
            model_settings["command_template"] = command_template
        return model_settings

    # auto-multi
    has_llm = any(detected.values())
    model_settings = {
        "backend_priority": ["codex", "claude", "opencode", "shell", "mock"],
        "backends": {
            "shell": {"enabled": True},
            "claude": {"enabled": detected["claude"]},
            "codex": {"enabled": detected["codex"]},
            "opencode": {"enabled": detected["opencode"]},
            "mock": {"enabled": True},
        },
    }
    if command_template:
        model_settings["command_template"] = command_template
    return model_settings


@app.command("init")
def init_cmd(interactive: bool = typer.Option(True, "--interactive/--no-interactive")):
    """Initialize app directories, DB, and optional starter resources."""
    paths = get_app_paths()
    if interactive and not paths.root.exists():
        create_home = typer.confirm(
            f"Create ExecForge home folder at '{paths.root}'?", default=True
        )
        if not create_home:
            typer.echo("Initialization cancelled.")
            raise typer.Exit(code=1)
    ensure_app_dirs(paths)
    if not paths.config_file.exists():
        save_config(paths, AppConfig())

    engine = make_engine(str(paths.db_file))
    init_db(engine)
    typer.echo(f"Initialized ExecForge home at {paths.root}")
    typer.echo(
        "Created: app.db, config.toml, logs/, prompt-sources/, runs/, cache/, locks/"
    )

    if not interactive:
        typer.echo("Next steps:")
        typer.echo("  1) execforge prompt-source add <name> <repo-url>")
        typer.echo("  2) execforge project add <name> <local-path>")
        typer.echo(
            "  3) execforge agent add <name> <prompt-source-name-or-id> <project-name-or-id>"
        )
        typer.echo("  4) execforge agent run <name-or-id>")
        return

    with session_scope(engine) as session:
        git = GitService()
        ps_service = PromptSourceService(session, paths, git)
        proj_service = ProjectService(session, git)
        agent_service = AgentService(session)

        typer.echo("")
        typer.echo("Welcome to ExecForge setup.")
        typer.echo(
            "This wizard creates a usable prompt source, project repo, and agent."
        )

        prompt_name = typer.prompt("Prompt source name", default="default-prompts")
        existing_source = ps_service.get(prompt_name)
        if existing_source:
            source = existing_source
            typer.echo(f"Using existing prompt source #{source.id}: {source.name}")
        else:
            repo_url = typer.prompt("Prompt source git URL (or local git path)")
            branch = typer.prompt("Prompt source branch", default="main")
            folder_scope = typer.prompt(
                "Prompt folder scope, repo-relative (blank for repo root, no leading /)",
                default="",
            )
            source = ps_service.add(
                prompt_name, repo_url, branch=branch, folder_scope=folder_scope or None
            )
            typer.echo(f"Created prompt source #{source.id}: {source.name}")

        if typer.confirm("Sync prompt source now?", default=True):
            bootstrap_missing_branch = typer.confirm(
                "If the configured branch does not exist remotely, create and push it?",
                default=False,
            )
            try:
                ps_service.sync(
                    source, bootstrap_missing_branch=bootstrap_missing_branch
                )
                discovered = TaskService(session).discover_and_upsert(source)
                typer.echo(f"Sync complete, discovered {discovered} task file(s)")
            except Exception as exc:
                message = str(exc)
                if (
                    "Remote branch" in message
                    and "not found" in message
                    and not bootstrap_missing_branch
                ):
                    if typer.confirm(
                        f"Branch '{source.branch}' is missing on origin. Create and push it now?",
                        default=False,
                    ):
                        try:
                            ps_service.sync(source, bootstrap_missing_branch=True)
                            discovered = TaskService(session).discover_and_upsert(
                                source
                            )
                            typer.echo(
                                f"Sync complete, discovered {discovered} task file(s)"
                            )
                        except Exception as retry_exc:
                            typer.echo(
                                f"Warning: prompt source sync failed: {retry_exc}"
                            )
                            typer.echo(
                                "You can retry later with: execforge prompt-source sync <name> --bootstrap-missing-branch"
                            )
                    else:
                        typer.echo(f"Warning: prompt source sync failed: {exc}")
                        typer.echo(
                            "You can retry later with: execforge prompt-source sync <name> --bootstrap-missing-branch"
                        )
                else:
                    typer.echo(f"Warning: prompt source sync failed: {exc}")
                    typer.echo(
                        "You can retry later with: execforge prompt-source sync <name> --bootstrap-missing-branch"
                    )

        project_name = typer.prompt("Project repo name", default="default-project")
        existing_project = proj_service.get(project_name)
        if existing_project:
            project = existing_project
            typer.echo(f"Using existing project repo #{project.id}: {project.name}")
        else:
            project_path = typer.prompt(
                "Local project repo path", default=str(Path.cwd())
            )
            while True:
                try:
                    project = proj_service.add(project_name, project_path)
                    break
                except Exception as exc:
                    typer.echo(f"That path could not be added: {exc}")
                    project_path = typer.prompt("Enter a valid local git repo path")
            typer.echo(f"Created project repo #{project.id}: {project.name}")

        detected = _detect_backend_binaries()
        typer.echo("Detected backend CLIs:")
        typer.echo(f"  - claude: {'yes' if detected['claude'] else 'no'}")
        typer.echo(f"  - codex: {'yes' if detected['codex'] else 'no'}")
        typer.echo(f"  - opencode: {'yes' if detected['opencode'] else 'no'}")

        profile = (
            typer.prompt(
                "Execution profile [auto/shell/mock]",
                default="auto",
            )
            .strip()
            .lower()
        )
        if profile not in {"auto", "shell", "mock"}:
            profile = "auto"

        default_command = typer.prompt(
            "Default shell command template (optional, used when a shell step has no command)",
            default="",
        )
        model_settings = _wizard_model_settings(
            profile=profile, command_template=default_command, detected=detected
        )

        validation_policy: list[dict] = []
        if typer.confirm("Add a validation command after each run?", default=False):
            validation_cmd = typer.prompt("Validation command (example: pytest -q)")
            validation_policy.append(
                {"type": "command", "name": "post-run", "command": validation_cmd}
            )

        safety_settings = {
            "dry_run": False,
            "max_files_changed": 100,
            "max_commits_per_run": 1,
            "require_clean_working_tree": False,
            "allow_push": False,
            "allow_branch_create": True,
            "allowed_commands": ["python", "pytest", "bash", "sh"],
            "timeout_seconds": 900,
            "max_retries": 0,
            "stop_on_validation_failure": True,
            "pull_project_before_run": True,
            "commit_after_each_step": True,
            "approval_mode": "semi-auto",
        }

        agent_name = typer.prompt("Agent name", default="default-agent")
        existing_agent = agent_service.get(agent_name)
        if existing_agent:
            agent = existing_agent
            typer.echo(f"Using existing agent #{agent.id}: {agent.name}")
        else:
            agent = agent_service.add(
                name=agent_name,
                prompt_source_id=source.id,
                project_repo_id=project.id,
                execution_backend="multi",
                model_settings=model_settings,
                validation_policy=validation_policy,
                safety_settings=safety_settings,
            )
            typer.echo(f"Created agent #{agent.id}: {agent.name}")

        typer.echo("")
        typer.echo("Setup complete.")
        typer.echo("Try these commands next:")
        typer.echo(f"  execforge prompt-source sync {source.name}")
        typer.echo("  execforge task list")
        typer.echo(f"  execforge agent run {agent.name}")


@prompt_source_app.command("add")
def prompt_source_add(
    name: str,
    repo_url: str,
    branch: str = "main",
    folder_scope: str = "",
    sync_strategy: str = "ff-only",
    clone_path: str = "",
):
    """Add a new prompt source definition."""
    paths, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = PromptSourceService(session, paths, git)
        item = svc.add(
            name=name,
            repo_url=repo_url,
            branch=branch,
            folder_scope=folder_scope or None,
            sync_strategy=sync_strategy,
            clone_path=clone_path or None,
        )
        typer.echo(f"Added prompt source #{item.id}: {item.name}")


@prompt_source_app.command("list")
def prompt_source_list():
    """List configured prompt sources."""
    paths, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = PromptSourceService(session, paths, git)
        for item in svc.list():
            typer.echo(
                f"{item.id}\t{item.name}\t{item.branch}\t{item.local_clone_path}\tactive={item.active}"
            )


@prompt_source_app.command("sync")
def prompt_source_sync(
    source: str,
    bootstrap_missing_branch: bool = typer.Option(
        False,
        "--bootstrap-missing-branch/--no-bootstrap-missing-branch",
        help="Create and push prompt branch if it does not exist on origin",
    ),
):
    """Sync a prompt source and discover task files."""
    paths, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = PromptSourceService(session, paths, git)
        item = svc.get(source)
        if not item:
            raise typer.Exit(code=2)
        try:
            svc.sync(item, bootstrap_missing_branch=bootstrap_missing_branch)
        except Exception as exc:
            message = str(exc)
            if (
                "Remote branch" in message
                and "not found" in message
                and not bootstrap_missing_branch
            ):
                typer.echo(message)
                typer.echo(
                    "Tip: re-run with --bootstrap-missing-branch to create and push the branch on origin"
                )
                raise typer.Exit(code=2)
            raise
        count = TaskService(session).discover_and_upsert(item)
        typer.echo(
            f"Synced prompt source '{item.name}' and discovered {count} task files"
        )
        if count == 0:
            typer.echo(
                "Hint: no task files found. Check folder scope and task file format."
            )
        else:
            typer.echo("Next: execforge task list")


@project_app.command("add")
def project_add(
    name: str,
    local_path: str,
    default_branch: str = "main",
    allowed_branch_pattern: str = "agent/*",
):
    """Register a local project repository."""
    _, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        item = ProjectService(session, git).add(
            name, local_path, default_branch, allowed_branch_pattern
        )
        typer.echo(f"Added project repo #{item.id}: {item.name}")


@project_app.command("list")
def project_list():
    """List registered project repositories."""
    _, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        for item in ProjectService(session, git).list():
            typer.echo(
                f"{item.id}\t{item.name}\t{item.local_path}\tdefault={item.default_branch}"
            )


@agent_app.command("add")
def agent_add(
    name: str,
    prompt_source: str,
    project_repo: str,
    execution_backend: str = "multi",
    command_template: str = "",
    enable_claude: bool = False,
    enable_codex: bool = False,
    enable_opencode: bool = False,
    enable_mock: bool = False,
):
    """Create an agent using prompt source and project (name or id)."""
    paths, _, engine, git, _ = _runtime()
    model_settings: dict[str, object] = {
        "backend_priority": ["codex", "claude", "opencode", "shell", "mock"],
        "backends": {
            "shell": {"enabled": True},
            "claude": {"enabled": enable_claude},
            "codex": {"enabled": enable_codex},
            "opencode": {"enabled": enable_opencode},
            "mock": {"enabled": True},
        },
    }
    if command_template:
        model_settings["command_template"] = command_template
    safety_settings = {
        "dry_run": False,
        "max_files_changed": 100,
        "max_commits_per_run": 1,
        "require_clean_working_tree": False,
        "allow_push": False,
        "allow_branch_create": True,
        "allowed_commands": ["python", "pytest", "bash", "sh"],
        "timeout_seconds": 900,
        "max_retries": 0,
        "stop_on_validation_failure": True,
        "pull_project_before_run": True,
        "commit_after_each_step": True,
        "approval_mode": "semi-auto",
    }
    with session_scope(engine) as session:
        prompt_service = PromptSourceService(session, paths, git)
        project_service = ProjectService(session, git)

        source = prompt_service.get(prompt_source)
        if not source:
            typer.echo(f"Prompt source not found: {prompt_source}")
            raise typer.Exit(code=2)

        project = project_service.get(project_repo)
        if not project:
            typer.echo(f"Project repo not found: {project_repo}")
            raise typer.Exit(code=2)

        item = AgentService(session).add(
            name=name,
            prompt_source_id=source.id,
            project_repo_id=project.id,
            execution_backend=execution_backend,
            model_settings=model_settings,
            safety_settings=safety_settings,
        )
        typer.echo(f"Added agent #{item.id}: {item.name}")


@agent_app.command("list")
def agent_list(
    compact: bool = typer.Option(
        False, "--compact", help="Show one-line summary instead of full JSON blocks"
    ),
):
    """List agents with full config blocks."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        agents = AgentService(session).list()
        for idx, a in enumerate(agents, start=1):
            prompt_source = session.get(PromptSourceORM, a.prompt_source_id)
            project = session.get(ProjectRepoORM, a.project_repo_id)

            if compact:
                typer.echo(
                    f"{a.name}\tbackend={a.execution_backend}\tprompt={prompt_source.name if prompt_source else '?'}\tproject={project.name if project else '?'}\tactive={a.active}"
                )
                continue

            payload = {
                "name": a.name,
                "active": a.active,
                "execution_backend": a.execution_backend,
                "task_selector_strategy": a.task_selector_strategy,
                "autonomy_level": a.autonomy_level,
                "max_steps": a.max_steps,
                "push_policy": a.push_policy,
                "prompt_source": {
                    "name": prompt_source.name if prompt_source else None,
                    "repo_url": prompt_source.repo_url if prompt_source else None,
                    "branch": prompt_source.branch if prompt_source else None,
                    "folder_scope": prompt_source.folder_scope
                    if prompt_source
                    else None,
                    "sync_strategy": prompt_source.sync_strategy
                    if prompt_source
                    else None,
                    "active": prompt_source.active if prompt_source else None,
                },
                "project": {
                    "name": project.name if project else None,
                    "local_path": project.local_path if project else None,
                    "default_branch": project.default_branch if project else None,
                    "allowed_branch_pattern": project.allowed_branch_pattern
                    if project
                    else None,
                    "active": project.active if project else None,
                },
                "model_settings": json.loads(a.model_settings_json or "{}"),
                "safety_settings": json.loads(a.safety_settings_json or "{}"),
                "validation_policy": json.loads(a.validation_policy_json or "[]"),
                "commit_policy": json.loads(a.commit_policy_json or "{}"),
            }
            typer.echo(json.dumps(payload, indent=2))
            if idx < len(agents):
                typer.echo("")


@agent_app.command("update")
def agent_update(
    agent: str,
    set_pair: list[str] = typer.Option(
        [],
        "--set",
        "-s",
        help="Update agent config with key=value (repeatable)",
    ),
):
    """Update agent configuration values."""
    if not set_pair:
        typer.echo("No updates provided. Use --set key=value")
        raise typer.Exit(code=2)
    updates: dict[str, str] = {}
    for pair in set_pair:
        if "=" not in pair:
            typer.echo(f"Invalid --set value '{pair}', expected key=value")
            raise typer.Exit(code=2)
        k, v = pair.split("=", 1)
        updates[k.strip()] = v.strip()

    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)
        updated = svc.update(item, updates)
        typer.echo(f"Updated agent '{updated.name}'")


@agent_app.command("delete")
def agent_delete(
    agent: str,
    yes: bool = typer.Option(False, "--yes", help="Delete without confirmation"),
):
    """Permanently delete an agent and its run history."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)

        if not yes:
            confirmed = typer.confirm(
                f"Permanently delete agent '{item.name}' and its run history?",
                default=False,
            )
            if not confirmed:
                typer.echo("Cancelled")
                return

        svc.delete_full(item)
        typer.echo(f"Deleted agent '{agent}'")


@agent_app.command("run")
def agent_run(
    agent: str,
    verbose: bool = typer.Option(
        False, "--verbose", help="Show backend/selection details"
    ),
    debug: bool = typer.Option(False, "--debug", help="Show debug stream logs"),
):
    """Run one execution cycle for an agent."""
    paths, config, engine, git, log_path = _runtime(
        console_debug=debug, force_debug_logging=debug
    )
    mode = "debug" if debug else ("verbose" if verbose else "default")
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)
        result = AgentRunner(
            session,
            paths,
            config,
            git,
            reporter=ConsoleReporter(mode=mode),
            log_path=str(log_path),
        ).run_once(item)
        if debug:
            typer.echo(json.dumps(result, indent=2))


@agent_app.command("loop")
def agent_loop(
    agent: str,
    interval_seconds: int = 30,
    max_iterations: int = 0,
    verbose: bool = typer.Option(
        False, "--verbose", help="Show backend/selection details"
    ),
    debug: bool = typer.Option(False, "--debug", help="Show debug stream logs"),
    only_new_prompts: bool = typer.Option(
        True,
        "--only-new-prompts/--all-eligible-prompts",
        help="Ignore tasks that already existed when loop started (default: only new prompts)",
    ),
    reset_only_new_baseline: bool = typer.Option(
        False,
        "--reset-only-new-baseline",
        help="Reset baseline for first loop run, then continue only-new mode",
    ),
):
    """Run an agent continuously on a polling interval."""
    paths, config, engine, git, log_path = _runtime(
        console_debug=debug, force_debug_logging=debug
    )
    mode = "debug" if debug else ("verbose" if verbose else "default")
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)
        AgentRunner(
            session,
            paths,
            config,
            git,
            reporter=ConsoleReporter(mode=mode),
            log_path=str(log_path),
        ).run_loop(
            item,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations or None,
            only_new_prompts=only_new_prompts,
            reset_only_new_baseline=reset_only_new_baseline,
        )


@task_app.command("list")
def task_list(status: str = ""):
    """List discovered tasks, optionally filtered by status."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        tasks = TaskService(session).list(status or None)
        for t in tasks:
            ref = t.external_id or f"task-{t.id}"
            typer.echo(f"{t.id}\t{ref}\t{t.status}\t{t.priority}\t{t.title}")


@task_app.command("inspect")
def task_inspect(task_id: int):
    """Inspect details for a single task."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        task = TaskService(session).get(task_id)
        if not task:
            typer.echo("Task not found")
            raise typer.Exit(code=2)
        typer.echo(f"id: {task.id}")
        typer.echo(f"title: {task.title}")
        typer.echo(f"status: {task.status}")
        typer.echo(f"priority: {task.priority}")
        typer.echo(f"source: {task.source_path}")
        typer.echo("description:")
        typer.echo(task.description)
        parsed = TaskService(session).parse_raw_task(task)
        if parsed.steps:
            typer.echo("steps:")
            for step in parsed.steps:
                prefs = (
                    ",".join(step.tool_preferences)
                    if step.tool_preferences
                    else "(default-priority)"
                )
                typer.echo(f"  - {step.id} [{step.type}] tools={prefs}")


@task_app.command("set-status")
def task_set_status(task_id: int, status: str):
    """Update task status (todo, ready, in_progress, done, failed, blocked)."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        service = TaskService(session)
        try:
            task = service.set_status_by_id(task_id, status)
        except ValueError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=2)
        if not task:
            typer.echo("Task not found")
            raise typer.Exit(code=2)
        ref = task.external_id or f"task-{task.id}"
        typer.echo(f"Updated {ref} to status={task.status}")


@task_app.command("retry")
def task_retry(task_id: int):
    """Set a task back to todo so it can run again."""
    task_set_status(task_id=task_id, status="todo")


@run_app.command("list")
def run_list(limit: int = 30):
    """List recent execution runs."""
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        runs = RunService(session).list(limit=limit)
        for r in runs:
            typer.echo(
                f"{r.id}\tagent={r.agent_id}\ttask={r.task_id}\tstatus={r.status}\tstart={r.started_at}\tcommit={r.commit_sha or '-'}"
            )


@config_app.command("show")
def config_show():
    """Show current app configuration (sensitive fields masked)."""
    paths = get_app_paths()
    config = load_config(paths)
    typer.echo(f"home: {paths.root}")
    typer.echo(f"db: {paths.db_file}")
    typer.echo(f"logs: {paths.logs_dir}")
    typer.echo(
        json.dumps(config_to_display_dict(config, mask_sensitive=True), indent=2)
    )


@config_app.command("set")
def config_set(
    key: str | None = typer.Argument(None),
    value: str | None = typer.Argument(None),
    set_pair: list[str] = typer.Option(
        [],
        "--set",
        "-s",
        help="Set config using key=value (repeatable)",
    ),
):
    """Set one or more app configuration values."""
    updates: dict[str, str] = {}
    if key and value is not None:
        updates[key] = value
    for pair in set_pair:
        if "=" not in pair:
            typer.echo(f"Invalid --set value '{pair}', expected key=value")
            raise typer.Exit(code=2)
        k, v = pair.split("=", 1)
        updates[k.strip()] = v.strip()
    if not updates:
        typer.echo("No config updates provided")
        raise typer.Exit(code=2)

    paths = get_app_paths()
    updated = update_config_values(paths, updates)
    typer.echo("Updated config:")
    typer.echo(
        json.dumps(config_to_display_dict(updated, mask_sensitive=True), indent=2)
    )


@config_app.command("reset")
def config_reset(
    key: list[str] = typer.Argument([], help="Config key(s) to reset"),
    all_keys: bool = typer.Option(
        False, "--all", help="Reset all keys to default values"
    ),
):
    """Reset one or more config keys to defaults."""
    if not all_keys and not key:
        typer.echo("Specify at least one key or pass --all")
        raise typer.Exit(code=2)

    paths = get_app_paths()
    updated = reset_config_values(paths, keys=None if all_keys else key)
    typer.echo("Reset config:")
    typer.echo(
        json.dumps(config_to_display_dict(updated, mask_sensitive=True), indent=2)
    )


@config_app.command("keys")
def config_keys():
    """List editable config keys and metadata."""
    schema = get_config_schema()
    for key, spec in schema.items():
        sensitive = "yes" if spec.sensitive else "no"
        typer.echo(
            f"{key}\ttype={spec.value_type.__name__}\tsensitive={sensitive}\tdefault={spec.default}"
        )


@app.command("doctor")
def doctor():
    """Run environment and dependency health checks."""
    paths, _, engine, git, log_path = _runtime()
    typer.echo("Doctor")
    typer.echo(f"  App home: {paths.root}")
    typer.echo(f"  DB file: {paths.db_file}")
    typer.echo(f"  Log file: {log_path}")
    with session_scope(engine):
        typer.echo("  SQLite: OK")
    try:
        git.ensure_git_repo(Path.cwd())
        typer.echo(f"  Git: OK ({Path.cwd()} is a repo)")
    except Exception:
        typer.echo("  Git: WARN (cwd is not a git repo)")
        typer.echo(
            "  Hint: run commands from your project repo when testing git behavior"
        )


@app.command("status")
def status():
    """Show a quick summary of current setup and last run."""
    paths, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        prompt_sources = PromptSourceService(session, paths, GitService()).list()
        projects = ProjectService(session, GitService()).list()
        agents = AgentService(session).list()
        runs = RunService(session).list(limit=1)

        typer.echo("Execforge Status")
        typer.echo(f"  Home: {paths.root}")
        typer.echo(f"  Prompt sources: {len(prompt_sources)}")
        typer.echo(f"  Project repos: {len(projects)}")
        typer.echo(f"  Agents: {len(agents)}")
        if runs:
            last = runs[0]
            typer.echo(
                f"  Last run: #{last.id} status={last.status} task={last.task_id} started={last.started_at}"
            )
        else:
            typer.echo("  Last run: none")

        if not prompt_sources:
            typer.echo("  Next: execforge prompt-source add <name> <repo-url>")
        elif not projects:
            typer.echo("  Next: execforge project add <name> <local-path>")
        elif not agents:
            typer.echo(
                "  Next: execforge agent add <name> <prompt-source-name-or-id> <project-name-or-id>"
            )
        else:
            typer.echo("  Next: execforge agent run <agent-name>")


@app.command("start")
def start():
    """Quick guidance for first-time and daily use."""
    typer.echo("Execforge Start")
    typer.echo("  1) execforge init")
    typer.echo("  2) execforge prompt-source add <name> <repo-url>")
    typer.echo("  3) execforge prompt-source sync <name>")
    typer.echo("  4) execforge project add <name> <local-path>")
    typer.echo(
        "  5) execforge agent add <name> <prompt-source-name-or-id> <project-name-or-id>"
    )
    typer.echo("  6) execforge agent run <name> or execforge agent loop <name>")
    typer.echo("")
    typer.echo("Run `execforge status` to see what is already configured.")


@app.callback()
def root_callback():
    """Autonomous repo orchestration CLI."""


def main() -> None:
    try:
        app()
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}")
        raise typer.Exit(code=2)
    except OrchestratorError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)
