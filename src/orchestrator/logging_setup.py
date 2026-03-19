from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path


def configure_logging(logs_dir: Path, level: str = "INFO") -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    log_file = logs_dir / f"orchestrator-{stamp}.log"

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s run_id=%(run_id)s agent=%(agent)s task=%(task)s %(message)s"
    )

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return log_file


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        base = {"run_id": "-", "agent": "-", "task": "-"}
        base.update(self.extra)
        base.update(extra)
        kwargs["extra"] = base
        return msg, kwargs
