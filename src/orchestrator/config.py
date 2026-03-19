from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import logging
import os
import tempfile
import tomllib
from typing import Any, Callable

from platformdirs import user_data_dir

from orchestrator.exceptions import ConfigError


APP_NAME = "agent-orchestrator"
logger = logging.getLogger("orchestrator.config")


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
    claude_api_key: str | None = None
    codex_api_key: str | None = None
    opencode_api_key: str | None = None


@dataclass(slots=True)
class ConfigFieldSpec:
    key: str
    value_type: type
    default: Any
    sensitive: bool = False
    validator: Callable[[Any], bool] | None = None
    description: str = ""


def _bool_from_text(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    raise ConfigError(f"Expected boolean value, got '{value}'")


def _cast_value(spec: ConfigFieldSpec, raw: Any) -> Any:
    if raw is None:
        return None
    if spec.value_type is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return _bool_from_text(raw)
        raise ConfigError(f"Config '{spec.key}' must be a boolean")
    if spec.value_type is int:
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"Config '{spec.key}' must be an integer") from exc
    if spec.value_type is str:
        return str(raw)
    return raw


def _validate_log_level(value: str) -> bool:
    return value.upper() in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _validate_timeout(value: int) -> bool:
    return 1 <= value <= 86400


def get_config_schema() -> dict[str, ConfigFieldSpec]:
    return {
        "log_level": ConfigFieldSpec(
            key="log_level",
            value_type=str,
            default="INFO",
            validator=_validate_log_level,
            description="Logging level",
        ),
        "default_timeout_seconds": ConfigFieldSpec(
            key="default_timeout_seconds",
            value_type=int,
            default=900,
            validator=_validate_timeout,
            description="Default run timeout in seconds",
        ),
        "default_require_clean_tree": ConfigFieldSpec(
            key="default_require_clean_tree",
            value_type=bool,
            default=True,
            description="Require clean working tree before run",
        ),
        "default_allow_push": ConfigFieldSpec(
            key="default_allow_push",
            value_type=bool,
            default=False,
            description="Allow push by default",
        ),
        "claude_api_key": ConfigFieldSpec(
            key="claude_api_key",
            value_type=str,
            default=None,
            sensitive=True,
            description="Optional Claude API key",
        ),
        "codex_api_key": ConfigFieldSpec(
            key="codex_api_key",
            value_type=str,
            default=None,
            sensitive=True,
            description="Optional Codex API key",
        ),
        "opencode_api_key": ConfigFieldSpec(
            key="opencode_api_key",
            value_type=str,
            default=None,
            sensitive=True,
            description="Optional OpenCode API key",
        ),
    }


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


def _normalize_loaded_data(data: dict[str, Any]) -> dict[str, Any]:
    schema = get_config_schema()
    normalized: dict[str, Any] = {}
    for key, spec in schema.items():
        if key not in data:
            continue
        value = _cast_value(spec, data[key])
        if spec.validator and value is not None and not spec.validator(value):
            raise ConfigError(f"Invalid value for '{key}': {value}")
        normalized[key] = value
    return normalized


def load_config(paths: AppPaths) -> AppConfig:
    if not paths.config_file.exists():
        return AppConfig()
    with paths.config_file.open("rb") as fh:
        data = tomllib.load(fh)
    normalized = _normalize_loaded_data(data)
    return AppConfig(**normalized)


def _serialize_toml(config: AppConfig) -> str:
    data = asdict(config)
    schema = get_config_schema()
    lines: list[str] = []
    for key, spec in schema.items():
        value = data.get(key)
        if value is None:
            continue
        if spec.value_type is bool:
            lines.append(f"{key} = {str(value).lower()}")
        elif spec.value_type is int:
            lines.append(f"{key} = {value}")
        else:
            escaped = str(value).replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    lines.append("")
    return "\n".join(lines)


def save_config(paths: AppPaths, config: AppConfig) -> None:
    text = _serialize_toml(config)
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(paths.config_file.parent)) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(paths.config_file)


def config_to_display_dict(config: AppConfig, mask_sensitive: bool = True) -> dict[str, Any]:
    data = asdict(config)
    schema = get_config_schema()
    out: dict[str, Any] = {}
    for key, spec in schema.items():
        value = data.get(key)
        if mask_sensitive and spec.sensitive and value:
            out[key] = "********"
        else:
            out[key] = value
    return out


def update_config_values(paths: AppPaths, updates: dict[str, str]) -> AppConfig:
    schema = get_config_schema()
    unknown = [k for k in updates if k not in schema]
    if unknown:
        known = ", ".join(sorted(schema.keys()))
        raise ConfigError(f"Unknown config key(s): {', '.join(unknown)}. Known keys: {known}")

    config = load_config(paths)
    data = asdict(config)
    changed_keys: list[str] = []

    for key, raw_value in updates.items():
        spec = schema[key]
        value = None if raw_value == "null" else _cast_value(spec, raw_value)
        if spec.validator and value is not None and not spec.validator(value):
            raise ConfigError(f"Invalid value for '{key}': {raw_value}")
        if data.get(key) != value:
            changed_keys.append(key)
        data[key] = value

    updated = AppConfig(**data)
    save_config(paths, updated)
    if changed_keys:
        logger.info("config updated: keys=%s", changed_keys)
    return updated


def reset_config_values(paths: AppPaths, keys: list[str] | None = None) -> AppConfig:
    schema = get_config_schema()
    target_keys = keys or list(schema.keys())
    unknown = [k for k in target_keys if k not in schema]
    if unknown:
        raise ConfigError(f"Unknown config key(s): {', '.join(unknown)}")

    config = load_config(paths)
    data = asdict(config)
    for key in target_keys:
        data[key] = schema[key].default
    updated = AppConfig(**data)
    save_config(paths, updated)
    logger.info("config reset: keys=%s", target_keys)
    return updated
