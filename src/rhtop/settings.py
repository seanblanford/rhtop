"""Non-secret preferences, stored atomically with private Unix permissions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_path, user_data_path

from .auth import private_write
from .errors import RhtopError

PANELS = ("account", "positions", "orders", "assets", "watchlists")
LAYOUTS = ("classic", "mirrored", "stacked")


@dataclass
class Settings:
    poll_seconds: int = 30
    layout: str = "classic"
    panels: list[str] = field(default_factory=lambda: list(PANELS))
    sort_descending: bool = False

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError
            settings = cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
            if type(settings.poll_seconds) is not int or not 10 <= settings.poll_seconds <= 3600:
                raise ValueError
            if settings.layout not in LAYOUTS:
                raise ValueError
            if (
                not isinstance(settings.panels, list)
                or not settings.panels
                or any(panel not in PANELS for panel in settings.panels)
                or len(set(settings.panels)) != len(settings.panels)
            ):
                raise ValueError
            if type(settings.sort_descending) is not bool:
                raise ValueError
            return settings
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RhtopError(
                "Cannot read settings. Repair or move settings.json and retry."
            ) from exc

    def save(self, path: Path) -> None:
        private_write(path, (json.dumps(asdict(self), indent=2) + "\n").encode())


def config_path() -> Path:
    return user_config_path("rhtop", appauthor=False) / "settings.json"


def data_path() -> Path:
    return user_data_path("rhtop", appauthor=False)
