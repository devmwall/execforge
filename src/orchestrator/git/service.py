from __future__ import annotations

from pathlib import Path
import re

from orchestrator.exceptions import RepoError
from orchestrator.utils.process import run_command


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._/-]+", "-", name).strip("-").lower()


class GitService:
    def __init__(self, timeout_seconds: int = 900):
        self.timeout_seconds = timeout_seconds

    def ensure_git_repo(self, path: Path) -> None:
        result = run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0 or "true" not in result.stdout:
            raise RepoError(f"Not a git repository: {path}")

    def is_clean(self, path: Path) -> bool:
        result = run_command(["git", "status", "--porcelain"], cwd=path, timeout=self.timeout_seconds)
        return result.code == 0 and result.stdout.strip() == ""

    def current_branch(self, path: Path) -> str:
        result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or "Failed to read current branch")
        return result.stdout.strip()

    def checkout_branch(self, path: Path, branch: str) -> None:
        result = run_command(["git", "checkout", branch], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or f"Failed to checkout branch {branch}")

    def checkout_or_create_branch(self, path: Path, branch: str, start_point: str, allow_create: bool) -> None:
        if self.local_branch_exists(path, branch):
            self.checkout_branch(path, branch)
            return
        if not allow_create:
            raise RepoError(f"Branch '{branch}' does not exist and branch creation is disabled")
        result = run_command(["git", "checkout", "-b", branch, start_point], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or f"Failed to create branch {branch} from {start_point}")

    def local_branch_exists(self, path: Path, branch: str) -> bool:
        result = run_command(["git", "show-ref", "--verify", f"refs/heads/{branch}"], cwd=path, timeout=self.timeout_seconds)
        return result.code == 0

    def remote_branch_exists(self, path: Path, branch: str) -> bool:
        remote = self.primary_remote(path)
        result = run_command(["git", "ls-remote", "--heads", remote, branch], cwd=path, timeout=self.timeout_seconds)
        return result.code == 0 and bool(result.stdout.strip())

    def remotes(self, path: Path) -> list[str]:
        result = run_command(["git", "remote"], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or "Failed to read git remotes")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def primary_remote(self, path: Path) -> str:
        remotes = self.remotes(path)
        if "origin" in remotes:
            return "origin"
        if remotes:
            return remotes[0]
        raise RepoError("No git remote configured for repository")

    def has_commits(self, path: Path) -> bool:
        result = run_command(["git", "rev-parse", "--verify", "HEAD"], cwd=path, timeout=self.timeout_seconds)
        return result.code == 0

    def checkout_or_create_tracking_branch(self, path: Path, branch: str, create_and_push_if_missing: bool) -> None:
        remote = self.primary_remote(path)
        if self.local_branch_exists(path, branch):
            self.checkout_branch(path, branch)
            return

        if self.remote_branch_exists(path, branch):
            fetch = run_command(["git", "fetch", remote, branch], cwd=path, timeout=self.timeout_seconds)
            if fetch.code != 0:
                raise RepoError(fetch.stderr.strip() or f"Failed to fetch {remote}/{branch}")
            result = run_command(
                ["git", "checkout", "-b", branch, f"{remote}/{branch}"],
                cwd=path,
                timeout=self.timeout_seconds,
            )
            if result.code != 0:
                raise RepoError(result.stderr.strip() or f"Failed to checkout remote branch {remote}/{branch}")
            upstream = run_command(
                ["git", "branch", "--set-upstream-to", f"{remote}/{branch}", branch],
                cwd=path,
                timeout=self.timeout_seconds,
            )
            if upstream.code != 0:
                raise RepoError(upstream.stderr.strip() or f"Failed to set upstream to {remote}/{branch}")
            return

        if not create_and_push_if_missing:
            raise RepoError(f"Remote branch '{branch}' not found")

        create_result = run_command(["git", "checkout", "-b", branch], cwd=path, timeout=self.timeout_seconds)
        if create_result.code != 0:
            raise RepoError(create_result.stderr.strip() or f"Failed to create branch {branch}")

        if not self.has_commits(path):
            bootstrap_commit = run_command(
                [
                    "git",
                    "-c",
                    "user.name=execforge",
                    "-c",
                    "user.email=execforge@local",
                    "commit",
                    "--allow-empty",
                    "-m",
                    f"chore(execforge): bootstrap branch {branch}",
                ],
                cwd=path,
                timeout=self.timeout_seconds,
            )
            if bootstrap_commit.code != 0:
                raise RepoError(
                    bootstrap_commit.stderr.strip()
                    or f"Created branch '{branch}' but failed to create bootstrap commit"
                )

        push_result = run_command(["git", "push", "-u", remote, branch], cwd=path, timeout=self.timeout_seconds)
        if push_result.code != 0:
            raise RepoError(
                push_result.stderr.strip()
                or f"Created local branch '{branch}' but failed to push it to {remote}"
            )

    def make_agent_branch_name(self, agent_name: str, task_ref: str) -> str:
        return f"agent/{_sanitize(agent_name)}/{_sanitize(task_ref)}"

    def commit_all(self, path: Path, message: str) -> str | None:
        if self.is_clean(path):
            return None
        add_result = run_command(["git", "add", "."], cwd=path, timeout=self.timeout_seconds)
        if add_result.code != 0:
            raise RepoError(add_result.stderr.strip() or "git add failed")
        commit_result = run_command(["git", "commit", "-m", message], cwd=path, timeout=self.timeout_seconds)
        if commit_result.code != 0:
            raise RepoError(commit_result.stderr.strip() or "git commit failed")
        sha_result = run_command(["git", "rev-parse", "HEAD"], cwd=path, timeout=self.timeout_seconds)
        if sha_result.code != 0:
            raise RepoError(sha_result.stderr.strip() or "Failed to read commit sha")
        return sha_result.stdout.strip()

    def push(self, path: Path, branch: str) -> None:
        remote = self.primary_remote(path)
        result = run_command(["git", "push", "-u", remote, branch], cwd=path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or "git push failed")

    def clone(self, repo_url: str, clone_path: Path, branch: str, bootstrap_missing_branch: bool = False) -> None:
        clone_path.parent.mkdir(parents=True, exist_ok=True)
        result = run_command(["git", "clone", "--branch", branch, repo_url, str(clone_path)], cwd=clone_path.parent)
        if result.code == 0:
            return

        missing_branch = "Remote branch" in result.stderr and "not found" in result.stderr
        if not missing_branch:
            raise RepoError(result.stderr.strip() or "git clone failed")

        fallback = run_command(["git", "clone", repo_url, str(clone_path)], cwd=clone_path.parent)
        if fallback.code != 0:
            raise RepoError(fallback.stderr.strip() or "git clone failed")

        if not bootstrap_missing_branch:
            raise RepoError(
                f"Remote branch '{branch}' not found. Re-run with missing-branch bootstrap enabled to create and push it."
            )
        self.checkout_or_create_tracking_branch(clone_path, branch, create_and_push_if_missing=True)

    def pull(
        self,
        repo_path: Path,
        strategy: str = "ff-only",
        branch: str | None = None,
        bootstrap_missing_branch: bool = False,
    ) -> None:
        remote = self.primary_remote(repo_path)
        if branch:
            self.checkout_or_create_tracking_branch(
                repo_path,
                branch,
                create_and_push_if_missing=bootstrap_missing_branch,
            )
        if strategy == "none":
            return
        if branch:
            cmd = ["git", "pull", "--ff-only", remote, branch] if strategy == "ff-only" else ["git", "pull", "--rebase", remote, branch]
        else:
            cmd = ["git", "pull", "--ff-only"] if strategy == "ff-only" else ["git", "pull", "--rebase"]
        result = run_command(cmd, cwd=repo_path, timeout=self.timeout_seconds)
        if result.code != 0:
            raise RepoError(result.stderr.strip() or "git pull failed")
