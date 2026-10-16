"""Preferências em $XDG_CONFIG_HOME/buds-studio/config.json.

No Flatpak, o XDG_CONFIG_HOME é o do sandbox (~/.var/app/<app-id>/config).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .. import APP_SLUG

SYSTEM_EQ_BANDS_HZ = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
SYSTEM_EQ_GAIN_LIMIT = 12.0


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_SLUG


@dataclass
class Config:
    last_device: str | None = None  # endereço do fone selecionado
    devices: list[str] = field(default_factory=list)  # fones adicionados ao app (endereços)
    device_presets: dict[str, int] = field(default_factory=dict)  # último preset por fone
    last_preset: int | None = None  # legado (antes de vários fones)
    theme: str = "system"  # "system", "light" ou "dark"
    reapply_preset_on_connect: bool = False
    auto_reconnect: bool = True
    language: str = "pt_BR"  # "pt_BR", "en" ou "auto"
    background: str = ""  # "" = fundo neutro; "builtin:<arquivo>" ou "user:<arquivo>"
    notify_connection: bool = True
    notify_battery: bool = True
    battery_low_threshold: int = 20
    tray_icon: bool = True
    autostart: bool = False
    audio_autoswitch: bool = False
    system_eq_enabled: bool = False
    system_eq_gains: list[float] = field(default_factory=lambda: [0.0] * len(SYSTEM_EQ_BANDS_HZ))

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or cls.path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        defaults = cls()
        values = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            expected = type(getattr(defaults, f.name))
            if getattr(defaults, f.name) is None or isinstance(value, expected) or (
                expected is float and isinstance(value, int)
            ):
                values[f.name] = value
        config = cls(**values)
        config._sanitize()
        return config

    def _sanitize(self) -> None:
        if not (isinstance(self.last_preset, int) and 0 <= self.last_preset <= 5):
            self.last_preset = None
        if self.language not in ("pt_BR", "en", "auto"):
            self.language = "pt_BR"
        if self.theme not in ("system", "light", "dark"):
            self.theme = "system"
        self.devices = [d for d in self.devices if isinstance(d, str) and d]
        if not self.devices and self.last_device:
            self.devices = [self.last_device]  # migração da versão com um fone só
        self.device_presets = {
            k: v for k, v in self.device_presets.items()
            if isinstance(k, str) and isinstance(v, int) and 0 <= v <= 5
        }
        if self.last_device and self.last_preset is not None:
            self.device_presets.setdefault(self.last_device, self.last_preset)
        self.battery_low_threshold = max(5, min(50, int(self.battery_low_threshold)))
        gains = [float(g) for g in self.system_eq_gains if isinstance(g, (int, float))]
        gains = (gains + [0.0] * len(SYSTEM_EQ_BANDS_HZ))[: len(SYSTEM_EQ_BANDS_HZ)]
        self.system_eq_gains = [max(-SYSTEM_EQ_GAIN_LIMIT, min(SYSTEM_EQ_GAIN_LIMIT, g)) for g in gains]

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
