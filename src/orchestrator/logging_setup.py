from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path


def configure_logging(logs_dir: Path, level: str = "INFO", console_debug: bool = False) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    log_file = logs_dir / f"orchestrator-{stamp}.log"

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s "
        "run=%(run_id)s agent=%(agent)s task=%(task)s "
        "base=%(base_branch)s branch=%(branch)s step=%(step)s "
        "%(message)s"
    )

    if console_debug:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.setLevel(level.upper())
        root.addHandler(stream)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level.upper())
    root.addHandler(file_handler)

    return log_file


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        raw_extra = kwargs.get("extra")
        extra = raw_extra if isinstance(raw_extra, dict) else {}
        base: dict[str, object] = {
            "run_id": "-",
            "agent": "-",
            "task": "-",
            "base_branch": "-",
            "branch": "-",
            "step": "-",
        }
        base.update(dict(self.extra or {}))
        base.update(extra)
        kwargs["extra"] = base
        return msg, kwargs
