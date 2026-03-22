from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from orchestrator.cli.main import app


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False
    )


def _ensure_git_identity(repo: Path) -> None:
    _git(["config", "user.email", "ci@example.com"], cwd=repo)
    _git(["config", "user.name", "CI User"], cwd=repo)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_result = _git(["init"], cwd=path)
    assert init_result.returncode == 0, init_result.stderr
    _ensure_git_identity(path)
    branch = _git(["branch", "--show-current"], cwd=path)
    assert branch.returncode == 0
    if branch.stdout.strip() != "main":
        checkout = _git(["checkout", "-b", "main"], cwd=path)
        # If main already exists, continue.
        if checkout.returncode != 0 and "already exists" not in checkout.stderr:
            assert checkout.returncode == 0, checkout.stderr


def _commit_all(repo: Path, message: str) -> None:
    add = _git(["add", "-A"], cwd=repo)
    assert add.returncode == 0, add.stderr
    commit = _git(["commit", "-m", message], cwd=repo)
    assert commit.returncode == 0, commit.stderr


def _write_prompt_task(prompt_repo: Path) -> None:
    task_text = """---
id: task-001
title: Smoke task
status: todo
priority: high
steps:
  - id: plan
    type: llm_plan
    tool_preferences: [mock]
    prompt_inline: Plan this smoke task.
  - id: test
    type: shell
    tool_preferences: [shell]
    command: python -c \"print('ok')\"
  - id: summarize
    type: llm_summary
    tool_preferences: [mock]
    prompt_inline: Summarize completion.
---

Execute smoke flow.
"""
    (prompt_repo / "tasks").mkdir(parents=True, exist_ok=True)
    (prompt_repo / "tasks" / "task-001.md").write_text(task_text, encoding="utf-8")


def _write_workspace_task(prompt_repo: Path) -> None:
    task_text = """---
id: ws-001
title: Workspace smoke task
status: todo
priority: high
steps:
  - id: summarize
    type: llm_summary
    tool_preferences: [mock]
    prompt_inline: Summarize completion.
---

Execute workspace smoke flow.
"""
    (prompt_repo / "tasks").mkdir(parents=True, exist_ok=True)
    (prompt_repo / "tasks" / "ws-001.md").write_text(task_text, encoding="utf-8")


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required for e2e smoke tests"
)
def test_execforge_e2e_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    app_home = tmp_path / "app-home"
    prompt_repo = tmp_path / "prompt-repo"
    project_repo = tmp_path / "project-repo"

    # Pre-create app home so `execforge init` does not ask for confirmation.
    app_home.mkdir(parents=True, exist_ok=True)

    _init_repo(prompt_repo)
    _write_prompt_task(prompt_repo)
    _commit_all(prompt_repo, "add smoke task")

    _init_repo(project_repo)
    (project_repo / "README.md").write_text("# project\n", encoding="utf-8")
    _commit_all(project_repo, "initial project commit")
    initial_head = _git(["rev-parse", "HEAD"], cwd=project_repo)
    assert initial_head.returncode == 0

    monkeypatch.setenv("AGENT_ORCHESTRATOR_HOME", str(app_home))

    wizard_input = (
        "\n".join(
            [
                "prompts",  # prompt source name
                str(prompt_repo),  # prompt source git url/path
                "",  # branch (default main)
                "tasks",  # folder scope
                "y",  # sync now
                "n",  # bootstrap missing branch
                "project",  # project name
                str(project_repo),  # project path
                "mock",  # execution profile
                "",  # default shell command template
                "n",  # add validation command
                "agent",  # agent name
            ]
        )
        + "\n"
    )

    result = runner.invoke(app, ["init"], input=wizard_input)
    assert result.exit_code == 0, result.output
    assert "Setup complete." in result.output

    for cmd in [
        ["prompt-source", "list"],
        ["project", "list"],
        ["agent", "list"],
        ["task", "list"],
        ["task", "inspect", "1"],
        ["config", "show"],
        ["doctor"],
    ]:
        cmd_result = runner.invoke(app, cmd)
        assert cmd_result.exit_code == 0, f"{' '.join(cmd)} failed: {cmd_result.output}"

    run_result = runner.invoke(app, ["agent", "run", "agent"])
    assert run_result.exit_code == 0, run_result.output
    assert "Run complete" in run_result.output

    run_list_result = runner.invoke(app, ["run", "list", "--limit", "5"])
    assert run_list_result.exit_code == 0, run_list_result.output
    assert "status=success" in run_list_result.output

    task_list_after = runner.invoke(app, ["task", "list"])
    assert task_list_after.exit_code == 0, task_list_after.output
    assert "\tdone\t" in task_list_after.output

    # Verify branch+commit happened in project repo.
    branch = _git(["branch", "--show-current"], cwd=project_repo)
    assert branch.returncode == 0
    assert branch.stdout.strip().startswith("agent/agent/task-001")

    head = _git(["rev-parse", "HEAD"], cwd=project_repo)
    assert head.returncode == 0
    assert head.stdout.strip() != initial_head.stdout.strip()


def test_execforge_init_non_interactive_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    app_home = tmp_path / "app-home"
    monkeypatch.setenv("AGENT_ORCHESTRATOR_HOME", str(app_home))

    result = runner.invoke(app, ["init", "--no-interactive"])
    assert result.exit_code == 0, result.output
    assert "Initialized ExecForge home" in result.output
    assert "Next steps:" in result.output
    assert (app_home / "app.db").exists()
    assert (app_home / "config.toml").exists()


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required for e2e smoke tests"
)
def test_workspace_mode_run_from_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    app_home = tmp_path / "app-home"
    prompt_repo = tmp_path / "prompt-repo"
    workspace_root = tmp_path / "workspace"
    repo_a = workspace_root / "repo-a"
    repo_b = workspace_root / "repo-b"

    _init_repo(prompt_repo)
    _write_workspace_task(prompt_repo)
    _commit_all(prompt_repo, "add workspace smoke task")

    workspace_root.mkdir(parents=True, exist_ok=True)
    _init_repo(repo_a)
    (repo_a / "README.md").write_text("# repo-a\n", encoding="utf-8")
    _commit_all(repo_a, "init repo-a")
    _init_repo(repo_b)
    (repo_b / "README.md").write_text("# repo-b\n", encoding="utf-8")
    _commit_all(repo_b, "init repo-b")

    repo_a_head_before = _git(["rev-parse", "HEAD"], cwd=repo_a)
    repo_b_head_before = _git(["rev-parse", "HEAD"], cwd=repo_b)
    assert repo_a_head_before.returncode == 0
    assert repo_b_head_before.returncode == 0

    monkeypatch.setenv("AGENT_ORCHESTRATOR_HOME", str(app_home))

    init_result = runner.invoke(app, ["init", "--no-interactive"])
    assert init_result.exit_code == 0, init_result.output

    add_source = runner.invoke(
        app,
        [
            "prompt-source",
            "add",
            "prompts",
            str(prompt_repo),
            "--branch",
            "main",
            "--folder-scope",
            "tasks",
        ],
    )
    assert add_source.exit_code == 0, add_source.output

    sync_source = runner.invoke(app, ["prompt-source", "sync", "prompts"])
    assert sync_source.exit_code == 0, sync_source.output

    add_workspace_project = runner.invoke(
        app,
        [
            "project",
            "add",
            "workspace",
            str(workspace_root),
            "--default-branch",
            "main",
            "--allowed-branch-pattern",
            "agent/*",
            "--workspace",
        ],
    )
    assert add_workspace_project.exit_code == 0, add_workspace_project.output

    add_agent = runner.invoke(
        app,
        [
            "agent",
            "add",
            "ws-agent",
            "prompts",
            "workspace",
            "--execution-backend",
            "multi",
        ],
    )
    assert add_agent.exit_code == 0, add_agent.output

    enable_workspace_mode = runner.invoke(
        app,
        [
            "agent",
            "update",
            "ws-agent",
            "--set",
            "safety_settings.workspace_mode=true",
        ],
    )
    assert enable_workspace_mode.exit_code == 0, enable_workspace_mode.output

    run_result = runner.invoke(app, ["agent", "run", "ws-agent"])
    assert run_result.exit_code == 0, run_result.output
    assert "Run complete" in run_result.output

    repo_a_branch_after = _git(["branch", "--show-current"], cwd=repo_a)
    repo_b_branch_after = _git(["branch", "--show-current"], cwd=repo_b)
    repo_a_head_after = _git(["rev-parse", "HEAD"], cwd=repo_a)
    repo_b_head_after = _git(["rev-parse", "HEAD"], cwd=repo_b)

    assert repo_a_branch_after.returncode == 0
    assert repo_b_branch_after.returncode == 0
    assert repo_a_branch_after.stdout.strip() == "main"
    assert repo_b_branch_after.stdout.strip() == "main"
    assert repo_a_head_after.returncode == 0
    assert repo_b_head_after.returncode == 0
    assert repo_a_head_after.stdout.strip() == repo_a_head_before.stdout.strip()
    assert repo_b_head_after.stdout.strip() == repo_b_head_before.stdout.strip()
