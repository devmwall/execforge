from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from orchestrator.git.service import GitService


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False)


def _must(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for e2e smoke tests")
def test_clone_creates_missing_branch_and_pushes(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    _must(_git(["init"], seed))
    _must(_git(["config", "user.email", "ci@example.com"], seed))
    _must(_git(["config", "user.name", "CI User"], seed))
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _must(_git(["add", "README.md"], seed))
    _must(_git(["commit", "-m", "seed"], seed))

    remote = tmp_path / "remote.git"
    _must(_git(["clone", "--bare", str(seed), str(remote)], tmp_path))

    clone_target = tmp_path / "prompt-clone"
    svc = GitService()
    svc.clone(str(remote), clone_target, "main", bootstrap_missing_branch=True)

    current = _git(["branch", "--show-current"], clone_target)
    _must(current)
    assert current.stdout.strip() == "main"

    heads = _git(["ls-remote", "--heads", "origin", "main"], clone_target)
    _must(heads)
    assert heads.stdout.strip(), "Expected origin/main to exist after bootstrap push"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for e2e smoke tests")
def test_clone_bootstraps_branch_for_empty_remote(tmp_path: Path) -> None:
    remote = tmp_path / "remote-empty.git"
    _must(_git(["init", "--bare", str(remote)], tmp_path))

    clone_target = tmp_path / "prompt-empty-clone"
    svc = GitService()
    svc.clone(str(remote), clone_target, "main", bootstrap_missing_branch=True)

    current = _git(["branch", "--show-current"], clone_target)
    _must(current)
    assert current.stdout.strip() == "main"

    heads = _git(["ls-remote", "--heads", "origin", "main"], clone_target)
    _must(heads)
    assert heads.stdout.strip(), "Expected origin/main to exist after empty-remote bootstrap"
