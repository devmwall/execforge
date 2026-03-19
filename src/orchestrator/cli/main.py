from __future__ import annotations

import json
from pathlib import Path
import shutil

import typer

from orchestrator.config import AppConfig, ensure_app_dirs, get_app_paths, load_config, save_config
from orchestrator.exceptions import ConfigError, OrchestratorError
from orchestrator.git.service import GitService
from orchestrator.logging_setup import configure_logging
from orchestrator.services.agent_runner import AgentRunner
from orchestrator.services.agent_service import AgentService
from orchestrator.services.project_service import ProjectService
from orchestrator.services.prompt_source_service import PromptSourceService
from orchestrator.services.run_service import RunService
from orchestrator.services.task_service import TaskService
from orchestrator.storage.db import init_db, make_engine, session_scope


app = typer.Typer(help="ExecForge: local multi-backend execution orchestrator")
prompt_source_app = typer.Typer(help="Manage prompt sources")
project_app = typer.Typer(help="Manage project repositories")
agent_app = typer.Typer(help="Manage and run agents")
task_app = typer.Typer(help="Inspect discovered tasks")
run_app = typer.Typer(help="Inspect execution runs")
config_app = typer.Typer(help="Configuration commands")

app.add_typer(prompt_source_app, name="prompt-source")
app.add_typer(project_app, name="project")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.add_typer(run_app, name="run")
app.add_typer(config_app, name="config")


def _runtime():
    paths = get_app_paths()
    ensure_app_dirs(paths)
    config = load_config(paths)
    log_path = configure_logging(paths.logs_dir, config.log_level)
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


def _wizard_model_settings(profile: str, command_template: str, detected: dict[str, bool]) -> dict[str, object]:
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
            "mock": {"enabled": not has_llm},
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
        create_home = typer.confirm(f"Create ExecForge home folder at '{paths.root}'?", default=True)
        if not create_home:
            typer.echo("Initialization cancelled.")
            raise typer.Exit(code=1)
    ensure_app_dirs(paths)
    if not paths.config_file.exists():
        save_config(paths, AppConfig())

    engine = make_engine(str(paths.db_file))
    init_db(engine)
    typer.echo(f"Initialized ExecForge home at {paths.root}")
    typer.echo("Created: app.db, config.toml, logs/, prompt-sources/, runs/, cache/, locks/")

    if not interactive:
        typer.echo("Next steps:")
        typer.echo("  1) execforge prompt-source add <name> <repo-url>")
        typer.echo("  2) execforge project add <name> <local-path>")
        typer.echo("  3) execforge agent add <name> <prompt-source-id> <project-repo-id>")
        typer.echo("  4) execforge agent run <name-or-id>")
        return

    with session_scope(engine) as session:
        git = GitService()
        ps_service = PromptSourceService(session, paths, git)
        proj_service = ProjectService(session, git)
        agent_service = AgentService(session)

        typer.echo("")
        typer.echo("Welcome to ExecForge setup.")
        typer.echo("This wizard creates a usable prompt source, project repo, and agent.")

        prompt_name = typer.prompt("Prompt source name", default="default-prompts")
        existing_source = ps_service.get(prompt_name)
        if existing_source:
            source = existing_source
            typer.echo(f"Using existing prompt source #{source.id}: {source.name}")
        else:
            repo_url = typer.prompt("Prompt source git URL (or local git path)")
            branch = typer.prompt("Prompt source branch", default="main")
            folder_scope = typer.prompt("Prompt folder scope (blank for repo root)", default="")
            source = ps_service.add(prompt_name, repo_url, branch=branch, folder_scope=folder_scope or None)
            typer.echo(f"Created prompt source #{source.id}: {source.name}")

        if typer.confirm("Sync prompt source now?", default=True):
            bootstrap_missing_branch = typer.confirm(
                "If the configured branch does not exist remotely, create and push it?",
                default=False,
            )
            try:
                ps_service.sync(source, bootstrap_missing_branch=bootstrap_missing_branch)
                discovered = TaskService(session).discover_and_upsert(source)
                typer.echo(f"Sync complete, discovered {discovered} task file(s)")
            except Exception as exc:
                message = str(exc)
                if "Remote branch" in message and "not found" in message and not bootstrap_missing_branch:
                    if typer.confirm(
                        f"Branch '{source.branch}' is missing on origin. Create and push it now?",
                        default=False,
                    ):
                        try:
                            ps_service.sync(source, bootstrap_missing_branch=True)
                            discovered = TaskService(session).discover_and_upsert(source)
                            typer.echo(f"Sync complete, discovered {discovered} task file(s)")
                        except Exception as retry_exc:
                            typer.echo(f"Warning: prompt source sync failed: {retry_exc}")
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
            project_path = typer.prompt("Local project repo path", default=str(Path.cwd()))
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

        profile = typer.prompt(
            "Execution profile [auto/shell/mock]",
            default="auto",
        ).strip().lower()
        if profile not in {"auto", "shell", "mock"}:
            profile = "auto"

        default_command = typer.prompt(
            "Default shell command template (optional, used when a shell step has no command)",
            default="",
        )
        model_settings = _wizard_model_settings(profile=profile, command_template=default_command, detected=detected)

        validation_policy: list[dict] = []
        if typer.confirm("Add a validation command after each run?", default=False):
            validation_cmd = typer.prompt("Validation command (example: pytest -q)")
            validation_policy.append({"type": "command", "name": "post-run", "command": validation_cmd})

        safety_settings = {
            "dry_run": False,
            "max_files_changed": 100,
            "max_commits_per_run": 1,
            "require_clean_working_tree": True,
            "allow_push": False,
            "allow_branch_create": True,
            "allowed_commands": ["python", "pytest", "bash", "sh"],
            "timeout_seconds": 900,
            "max_retries": 0,
            "stop_on_validation_failure": True,
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
    paths, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = PromptSourceService(session, paths, git)
        for item in svc.list():
            typer.echo(f"{item.id}\t{item.name}\t{item.branch}\t{item.local_clone_path}\tactive={item.active}")


@prompt_source_app.command("sync")
def prompt_source_sync(
    source: str,
    bootstrap_missing_branch: bool = typer.Option(
        False,
        "--bootstrap-missing-branch/--no-bootstrap-missing-branch",
        help="Create and push prompt branch if it does not exist on origin",
    ),
):
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
            if "Remote branch" in message and "not found" in message and not bootstrap_missing_branch:
                typer.echo(message)
                typer.echo(
                    "Tip: re-run with --bootstrap-missing-branch to create and push the branch on origin"
                )
                raise typer.Exit(code=2)
            raise
        count = TaskService(session).discover_and_upsert(item)
        typer.echo(f"Synced prompt source '{item.name}' and discovered {count} task files")


@project_app.command("add")
def project_add(name: str, local_path: str, default_branch: str = "main", allowed_branch_pattern: str = "agent/*"):
    _, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        item = ProjectService(session, git).add(name, local_path, default_branch, allowed_branch_pattern)
        typer.echo(f"Added project repo #{item.id}: {item.name}")


@project_app.command("list")
def project_list():
    _, _, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        for item in ProjectService(session, git).list():
            typer.echo(f"{item.id}\t{item.name}\t{item.local_path}\tdefault={item.default_branch}")


@agent_app.command("add")
def agent_add(
    name: str,
    prompt_source_id: int,
    project_repo_id: int,
    execution_backend: str = "multi",
    command_template: str = "",
    enable_claude: bool = False,
    enable_codex: bool = False,
    enable_opencode: bool = False,
    enable_mock: bool = False,
):
    _, _, engine, _, _ = _runtime()
    model_settings: dict[str, object] = {
        "backend_priority": ["codex", "claude", "opencode", "shell", "mock"],
        "backends": {
            "shell": {"enabled": True},
            "claude": {"enabled": enable_claude},
            "codex": {"enabled": enable_codex},
            "opencode": {"enabled": enable_opencode},
            "mock": {"enabled": enable_mock or execution_backend == "mock"},
        },
    }
    if command_template:
        model_settings["command_template"] = command_template
    safety_settings = {
        "dry_run": False,
        "max_files_changed": 100,
        "max_commits_per_run": 1,
        "require_clean_working_tree": True,
        "allow_push": False,
        "allow_branch_create": True,
        "allowed_commands": ["python", "pytest", "bash", "sh"],
        "timeout_seconds": 900,
        "max_retries": 0,
        "stop_on_validation_failure": True,
        "approval_mode": "semi-auto",
    }
    with session_scope(engine) as session:
        item = AgentService(session).add(
            name=name,
            prompt_source_id=prompt_source_id,
            project_repo_id=project_repo_id,
            execution_backend=execution_backend,
            model_settings=model_settings,
            safety_settings=safety_settings,
        )
        typer.echo(f"Added agent #{item.id}: {item.name}")


@agent_app.command("list")
def agent_list():
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        for a in AgentService(session).list():
            typer.echo(
                f"{a.id}\t{a.name}\tprompt={a.prompt_source_id}\tproject={a.project_repo_id}\tbackend={a.execution_backend}"
            )


@agent_app.command("run")
def agent_run(agent: str):
    paths, config, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)
        result = AgentRunner(session, paths, config, git).run_once(item)
        typer.echo(json.dumps(result, indent=2))


@agent_app.command("loop")
def agent_loop(
    agent: str,
    interval_seconds: int = 30,
    max_iterations: int = 0,
    only_new_prompts: bool = typer.Option(
        False,
        "--only-new-prompts/--all-eligible-prompts",
        help="Ignore tasks that already existed when loop started",
    ),
):
    paths, config, engine, git, _ = _runtime()
    with session_scope(engine) as session:
        svc = AgentService(session)
        item = svc.get(agent)
        if not item:
            typer.echo("Agent not found")
            raise typer.Exit(code=2)
        AgentRunner(session, paths, config, git).run_loop(
            item,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations or None,
            only_new_prompts=only_new_prompts,
        )


@task_app.command("list")
def task_list(status: str = ""):
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        tasks = TaskService(session).list(status or None)
        for t in tasks:
            ref = t.external_id or f"task-{t.id}"
            typer.echo(f"{t.id}\t{ref}\t{t.status}\t{t.priority}\t{t.title}")


@task_app.command("inspect")
def task_inspect(task_id: int):
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
                prefs = ",".join(step.tool_preferences) if step.tool_preferences else "(default-priority)"
                typer.echo(f"  - {step.id} [{step.type}] tools={prefs}")


@run_app.command("list")
def run_list(limit: int = 30):
    _, _, engine, _, _ = _runtime()
    with session_scope(engine) as session:
        runs = RunService(session).list(limit=limit)
        for r in runs:
            typer.echo(
                f"{r.id}\tagent={r.agent_id}\ttask={r.task_id}\tstatus={r.status}\tstart={r.started_at}\tcommit={r.commit_sha or '-'}"
            )


@config_app.command("show")
def config_show():
    paths = get_app_paths()
    config = load_config(paths)
    typer.echo(f"home: {paths.root}")
    typer.echo(f"db: {paths.db_file}")
    typer.echo(f"logs: {paths.logs_dir}")
    typer.echo(json.dumps(config.__dict__, indent=2))


@app.command("doctor")
def doctor():
    paths, _, engine, git, log_path = _runtime()
    typer.echo(f"app_home\tOK\t{paths.root}")
    typer.echo(f"db_file\tOK\t{paths.db_file}")
    typer.echo(f"log_file\tOK\t{log_path}")
    with session_scope(engine):
        typer.echo("sqlite\tOK\tconnected")
    try:
        git.ensure_git_repo(Path.cwd())
        typer.echo(f"git\tOK\t{Path.cwd()} is repo")
    except Exception:
        typer.echo("git\tWARN\tcwd is not a git repo")


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
