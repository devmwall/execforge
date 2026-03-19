from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import AppPaths
from orchestrator.git.service import GitService
from orchestrator.storage.models import PromptSourceORM


class PromptSourceService:
    def __init__(self, session: Session, paths: AppPaths, git: GitService):
        self.session = session
        self.paths = paths
        self.git = git

    def add(
        self,
        name: str,
        repo_url: str,
        branch: str = "main",
        folder_scope: str | None = None,
        sync_strategy: str = "ff-only",
        clone_path: str | None = None,
    ) -> PromptSourceORM:
        clone = Path(clone_path) if clone_path else self.paths.prompt_sources_dir / name
        item = PromptSourceORM(
            name=name,
            repo_url=repo_url,
            local_clone_path=str(clone),
            branch=branch,
            folder_scope=folder_scope,
            sync_strategy=sync_strategy,
            active=True,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list(self) -> list[PromptSourceORM]:
        return list(self.session.scalars(select(PromptSourceORM).order_by(PromptSourceORM.id)).all())

    def get(self, source_id_or_name: str) -> PromptSourceORM | None:
        stmt = select(PromptSourceORM).where(PromptSourceORM.name == source_id_or_name)
        source = self.session.scalar(stmt)
        if source:
            return source
        if source_id_or_name.isdigit():
            return self.session.get(PromptSourceORM, int(source_id_or_name))
        return None

    def sync(self, source: PromptSourceORM, bootstrap_missing_branch: bool = False) -> None:
        path = Path(source.local_clone_path)
        if not path.exists():
            self.git.clone(source.repo_url, path, source.branch, bootstrap_missing_branch=bootstrap_missing_branch)
        else:
            self.git.ensure_git_repo(path)
            self.git.pull(
                path,
                source.sync_strategy,
                branch=source.branch,
                bootstrap_missing_branch=bootstrap_missing_branch,
            )
