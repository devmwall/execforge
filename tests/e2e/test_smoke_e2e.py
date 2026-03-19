from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from orchestrator.cli.main import app


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False)


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for e2e smoke tests")
def test_execforge_e2e_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    app_home = tmp_path / "app-home"
    prompt_repo = tmp_path / "prompt-repo"
    project_repo = tmp_path / "project-repo"

    _init_repo(prompt_repo)
    _write_prompt_task(prompt_repo)
    _commit_all(prompt_repo, "add smoke task")

    _init_repo(project_repo)
    (project_repo / "README.md").write_text("# project\n", encoding="utf-8")
    _commit_all(project_repo, "initial project commit")

    monkeypatch.setenv("AGENT_ORCHESTRATOR_HOME", str(app_home))

    wizard_input = "\n".join(
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
    ) + "\n"

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
    payload = json.loads(run_result.output)
    assert payload["status"] == "success"
    assert payload["commit"]

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
    assert head.stdout.strip() == payload["commit"]


def test_execforge_init_non_interactive_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    app_home = tmp_path / "app-home"
    monkeypatch.setenv("AGENT_ORCHESTRATOR_HOME", str(app_home))

    result = runner.invoke(app, ["init", "--no-interactive"])
    assert result.exit_code == 0, result.output
    assert "Initialized ExecForge home" in result.output
    assert "Next steps:" in result.output
    assert (app_home / "app.db").exists()
    assert (app_home / "config.toml").exists()
