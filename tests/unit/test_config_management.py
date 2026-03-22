from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.config import (
    AppPaths,
    config_to_display_dict,
    load_config,
    reset_config_values,
    update_config_values,
)
from orchestrator.exceptions import ConfigError


def _paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "home"
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


def test_load_defaults_when_config_missing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cfg = load_config(paths)
    assert cfg.log_level == "INFO"
    assert cfg.default_timeout_seconds == 900


def test_update_valid_keys_persists(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    updated = update_config_values(
        paths,
        {
            "log_level": "DEBUG",
            "default_timeout_seconds": "30",
            "default_allow_push": "true",
        },
    )
    assert updated.log_level == "DEBUG"
    assert updated.default_timeout_seconds == 30
    assert updated.default_allow_push is True

    loaded = load_config(paths)
    assert loaded.log_level == "DEBUG"
    assert loaded.default_timeout_seconds == 30
    assert loaded.default_allow_push is True


def test_reject_invalid_updates(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(ConfigError):
        update_config_values(paths, {"unknown_key": "x"})

    with pytest.raises(ConfigError):
        update_config_values(paths, {"default_timeout_seconds": "abc"})

    with pytest.raises(ConfigError):
        update_config_values(paths, {"log_level": "LOUD"})


def test_display_dict_contains_config_fields(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cfg = load_config(paths)
    display = config_to_display_dict(cfg, mask_sensitive=True)
    assert "log_level" in display
    assert "default_timeout_seconds" in display
    assert "default_require_clean_tree" in display
    assert "default_allow_push" in display


def test_reset_defaults(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    cfg = update_config_values(
        paths, {"default_allow_push": "true", "log_level": "DEBUG"}
    )
    assert cfg.default_allow_push is True
    assert cfg.log_level == "DEBUG"

    reset = reset_config_values(paths, keys=["default_allow_push"])
    assert reset.default_allow_push is False
    assert reset.log_level == "DEBUG"

    reset_all = reset_config_values(paths, keys=None)
    assert reset_all.default_allow_push is False
    assert reset_all.log_level == "INFO"
