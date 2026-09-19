"""Persistencia de configuracion de cadenaL en ~/.config/cadenal/config.json"""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "cadenal"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = _config_dir() / "config.json"

DEFAULT_SINK_NAME = "cadenal_mix"
DEFAULT_DESCRIPTION = "CadenaL - Mezcla de audio"


@dataclass
class Config:
    sink_name: str = DEFAULT_SINK_NAME
    description: str = DEFAULT_DESCRIPTION
    # nombres de aplicaciones (application.name) a ignorar, no se moveran
    exclude_apps: List[str] = field(default_factory=list)
    # sinks fisicos detectados en el ultimo escaneo (solo informativo)
    known_physical_sinks: List[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return cls(**{**asdict(cls()), **data})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
