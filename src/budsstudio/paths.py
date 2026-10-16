"""Onde ficam os arquivos de dados (layouts .ui, CSS e fundos)."""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def data_dir() -> Path:
    env = os.environ.get("BUDS_STUDIO_DATADIR")
    if env:
        return Path(env)
    installed = _PKG.parent / "data"  # <prefix>/share/buds-studio/data
    if (installed / "ui").is_dir():
        return installed
    return _PKG.parent.parent / "data"  # repositório: <repo>/data


def ui_file(name: str) -> str:
    return str(data_dir() / "ui" / name)


def style_file() -> Path:
    return data_dir() / "style.css"


def backgrounds_dir() -> Path:
    return data_dir() / "backgrounds"
