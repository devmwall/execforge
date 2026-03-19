from __future__ import annotations

import json

from orchestrator.backends.base import ExecutionBackend
from orchestrator.backends.llm_cli_backend import LlmCliBackend
from orchestrator.backends.mock_backend import MockBackend
from orchestrator.backends.shell_backend import ShellBackend
from orchestrator.exceptions import ConfigError
from orchestrator.storage.models import AgentORM


def build_backend_registry(agent: AgentORM) -> dict[str, ExecutionBackend]:
    settings = json.loads(agent.model_settings_json or "{}")
    safety = json.loads(agent.safety_settings_json or "{}")
    backends_cfg = settings.get("backends", {})

    registry: dict[str, ExecutionBackend] = {}

    shell_cfg = backends_cfg.get("shell", {})
    if agent.execution_backend == "shell" or shell_cfg.get("enabled", True):
        command_template = settings.get("command_template") or shell_cfg.get("command_template")
        allowed = shell_cfg.get("allowed_commands", safety.get("allowed_commands", []))
        registry["shell"] = ShellBackend(command_template=command_template, allowed_commands=allowed)

    for tool, defaults in {
        "claude": {"binary": "claude", "args": ["-p"]},
        "codex": {"binary": "codex", "args": ["exec", "--prompt"]},
        "opencode": {"binary": "opencode", "args": ["run", "--prompt"]},
    }.items():
        cfg = backends_cfg.get(tool, {})
        if not cfg.get("enabled", False):
            continue
        registry[tool] = LlmCliBackend(
            name=tool,
            binary=cfg.get("binary", defaults["binary"]),
            args=list(cfg.get("args", defaults["args"])),
            prompt_arg_template=cfg.get("prompt_arg_template", "{prompt}"),
            requires_binary=bool(cfg.get("requires_binary", True)),
        )

    registry["mock"] = MockBackend()

    if not registry:
        raise ConfigError("No execution backends are enabled for this agent")
    return registry


def default_backend_priority(agent: AgentORM) -> list[str]:
    settings = json.loads(agent.model_settings_json or "{}")
    priority = list(settings.get("backend_priority", []) or [])
    return priority or ["codex", "claude", "opencode", "shell", "mock"]
