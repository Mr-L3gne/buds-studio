"""Iniciar com o sistema (minimizado) pelo portal Background.

No Flatpak o portal cria a entrada de autostart; fora dele, grava um .desktop em
~/.config/autostart.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from gi.repository import GLib

from .. import APP_ID

AUTOSTART_ARGS = ["--background"]


def in_flatpak() -> bool:
    return bool(os.environ.get("FLATPAK_ID")) or Path("/.flatpak-info").exists()


def set_autostart(enabled: bool, reason: str, window, on_done: Callable[[bool, str], None]) -> None:
    if in_flatpak():
        _portal(enabled, reason, window, on_done)
    else:
        _desktop_file(enabled, on_done)


def _portal(enabled: bool, reason: str, window, on_done) -> None:
    try:
        import gi

        gi.require_version("Xdp", "1.0")
        gi.require_version("XdpGtk4", "1.0")
        from gi.repository import Xdp, XdpGtk4
    except (ImportError, ValueError) as exc:
        on_done(False, str(exc))
        return
    portal = Xdp.Portal()
    parent = XdpGtk4.parent_new_gtk(window) if window is not None else None
    flags = Xdp.BackgroundFlags.AUTOSTART if enabled else Xdp.BackgroundFlags.NONE
    command = ["buds-studio", *AUTOSTART_ARGS]

    def finished(p, result):
        try:
            ok = p.request_background_finish(result)
            on_done(bool(ok), "")
        except GLib.Error as exc:
            on_done(False, exc.message)

    portal.request_background(parent, reason, command, flags, None, finished)


def _desktop_file(enabled: bool, on_done) -> None:
    path = Path(GLib.get_user_config_dir()) / "autostart" / f"{APP_ID}.desktop"
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "[Desktop Entry]\nType=Application\nName=Buds Studio\n"
                f"Exec=buds-studio {' '.join(AUTOSTART_ARGS)}\nIcon={APP_ID}\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
        elif path.exists():
            path.unlink()
        on_done(True, "")
    except OSError as exc:
        on_done(False, str(exc))
