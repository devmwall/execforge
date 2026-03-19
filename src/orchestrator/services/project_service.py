from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.git.service import GitService
from orchestrator.storage.models import ProjectRepoORM


class ProjectService:
    def __init__(self, session: Session, git: GitService):
        self.session = session
        self.git = git

    def add(
        self,
        name: str,
        local_path: str,
        default_branch: str = "main",
        allowed_branch_pattern: str = "agent/*",
    ) -> ProjectRepoORM:
        repo_path = Path(local_path).expanduser().resolve()
        self.git.ensure_git_repo(repo_path)
        item = ProjectRepoORM(
            name=name,
            local_path=str(repo_path),
            default_branch=default_branch,
            allowed_branch_pattern=allowed_branch_pattern,
            active=True,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list(self) -> list[ProjectRepoORM]:
        return list(self.session.scalars(select(ProjectRepoORM).order_by(ProjectRepoORM.id)).all())

    def get(self, repo_id_or_name: str) -> ProjectRepoORM | None:
        stmt = select(ProjectRepoORM).where(ProjectRepoORM.name == repo_id_or_name)
        item = self.session.scalar(stmt)
        if item:
            return item
        if repo_id_or_name.isdigit():
            return self.session.get(ProjectRepoORM, int(repo_id_or_name))
        return None
