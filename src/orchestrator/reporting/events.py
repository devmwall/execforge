from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def clean_context(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        cleaned[key] = value
    return cleaned


@dataclass(slots=True)
class LogEvent:
    name: str
    level: str = "info"
    phase_index: int | None = None
    phase_total: int | None = None
    title: str | None = None
    message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "level": self.level,
        }
        if self.phase_index is not None:
            payload["phase_index"] = self.phase_index
        if self.phase_total is not None:
            payload["phase_total"] = self.phase_total
        if self.title:
            payload["title"] = self.title
        if self.message:
            payload["message"] = self.message
        payload["context"] = clean_context(self.context)
        return payload
