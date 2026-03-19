from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PromptSourceORM(Base):
    __tablename__ = "prompt_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_clone_path: Mapped[str] = mapped_column(String(500), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), default="main")
    folder_scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sync_strategy: Mapped[str] = mapped_column(String(32), default="ff-only")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectRepoORM(Base):
    __tablename__ = "project_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    local_path: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    allowed_branch_pattern: Mapped[str] = mapped_column(String(200), default="agent/*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentORM(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    prompt_source_id: Mapped[int] = mapped_column(ForeignKey("prompt_sources.id"), nullable=False)
    project_repo_id: Mapped[int] = mapped_column(ForeignKey("project_repos.id"), nullable=False)
    task_selector_strategy: Mapped[str] = mapped_column(String(64), default="priority_then_oldest")
    execution_backend: Mapped[str] = mapped_column(String(64), default="mock")
    model_settings_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_policy_json: Mapped[str] = mapped_column(Text, default="[]")
    commit_policy_json: Mapped[str] = mapped_column(Text, default="{}")
    push_policy: Mapped[str] = mapped_column(String(32), default="never")
    autonomy_level: Mapped[str] = mapped_column(String(32), default="semi-auto")
    max_steps: Mapped[int] = mapped_column(Integer, default=20)
    safety_settings_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskORM(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("prompt_source_id", "source_path", name="uq_task_source_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_source_id: Mapped[int] = mapped_column(ForeignKey("prompt_sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_path: Mapped[str] = mapped_column(String(600), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    labels_json: Mapped[str] = mapped_column(Text, default="[]")
    priority: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="todo")
    dependencies_json: Mapped[str] = mapped_column(Text, default="[]")
    target_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    target_repo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acceptance_criteria_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_content: Mapped[str] = mapped_column(Text, default="")
    last_seen_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RunORM(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    summary: Mapped[str] = mapped_column(Text, default="")
    tool_invocations_json: Mapped[str] = mapped_column(Text, default="[]")
    validation_results_json: Mapped[str] = mapped_column(Text, default="[]")
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logs_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
