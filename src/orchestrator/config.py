from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import tomllib

from platformdirs import user_data_dir


APP_NAME = "agent-orchestrator"


@dataclass(slots=True)
class AppPaths:
    root: Path
    db_file: Path
    config_file: Path
    logs_dir: Path
    prompt_sources_dir: Path
    runs_dir: Path
    cache_dir: Path
    lock_dir: Path


@dataclass(slots=True)
class AppConfig:
    log_level: str = "INFO"
    default_timeout_seconds: int = 900
    default_require_clean_tree: bool = True
    default_allow_push: bool = False


def get_app_paths() -> AppPaths:
    override = os.environ.get("AGENT_ORCHESTRATOR_HOME") or os.environ.get("ORCHESTRATOR_HOME")
    root = Path(override).expanduser() if override else Path(user_data_dir(APP_NAME, APP_NAME))
    return AppPaths(
        root=root,
        db_file=root / "app.db",
        config_file=root / "config.toml",
        logs_dir=root / "logs",
        prompt_sources_dir=root / "prompt-sources",
        runs_dir=root / "runs",
        cache_dir=root / "cache",
        lock_dir=root / "locks",
    )


def ensure_app_dirs(paths: AppPaths) -> None:
    for p in [
        paths.root,
        paths.logs_dir,
        paths.prompt_sources_dir,
        paths.runs_dir,
        paths.cache_dir,
        paths.lock_dir,
    ]:
        p.mkdir(parents=True, exist_ok=True)


def load_config(paths: AppPaths) -> AppConfig:
    if not paths.config_file.exists():
        return AppConfig()
    with paths.config_file.open("rb") as fh:
        data = tomllib.load(fh)
    return AppConfig(**{k: v for k, v in data.items() if hasattr(AppConfig, k)})


def save_config(paths: AppPaths, config: AppConfig) -> None:
    data = asdict(config)
    lines = [
        f'log_level = "{data["log_level"]}"',
        f"default_timeout_seconds = {data['default_timeout_seconds']}",
        f"default_require_clean_tree = {str(data['default_require_clean_tree']).lower()}",
        f"default_allow_push = {str(data['default_allow_push']).lower()}",
        "",
    ]
    paths.config_file.write_text("\n".join(lines), encoding="utf-8")
