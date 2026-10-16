"""Carrega data/style.css e aplica a imagem de fundo escolhida."""

from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gdk, Gtk

from ..paths import backgrounds_dir, style_file
from ..services.config import config_dir

IMAGE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".webp")

_background_provider: Gtk.CssProvider | None = None


def load_stylesheet() -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    path = style_file()
    if path.exists():
        provider.load_from_path(str(path))
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def user_backgrounds_dir() -> Path:
    return config_dir() / "backgrounds"


def builtin_backgrounds() -> list[Path]:
    folder = backgrounds_dir()
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def user_backgrounds() -> list[Path]:
    folder = user_backgrounds_dir()
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def resolve_background(value: str) -> Path | None:
    """Converte o valor da config ("builtin:x.svg" / "user:y.png") em caminho existente."""
    if not value or ":" not in value:
        return None
    kind, name = value.split(":", 1)
    folder = backgrounds_dir() if kind == "builtin" else user_backgrounds_dir() if kind == "user" else None
    if folder is None or "/" in name:
        return None
    path = folder / name
    return path if path.is_file() else None


def apply_background(widget: Gtk.Widget, value: str) -> None:
    """Liga a classe .has-image e define --app-background-image. O resto fica no style.css."""
    global _background_provider
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _background_provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _background_provider)
        _background_provider = None
    path = resolve_background(value)
    if path is None:
        widget.remove_css_class("has-image")
        return
    uri = path.resolve().as_uri().replace('"', "%22")
    provider = Gtk.CssProvider()
    provider.load_from_string(f'.app-background {{ --app-background-image: url("{uri}"); }}')
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _background_provider = provider
    widget.add_css_class("has-image")


THEMES = ("system", "light", "dark")


def color_scheme_for(theme: str) -> Adw.ColorScheme:
    return {
        "light": Adw.ColorScheme.FORCE_LIGHT,
        "dark": Adw.ColorScheme.FORCE_DARK,
    }.get(theme, Adw.ColorScheme.DEFAULT)


def apply_theme(theme: str) -> None:
    """Aplica o tema na hora (Claro, Escuro ou Seguir o sistema)."""
    Adw.StyleManager.get_default().set_color_scheme(color_scheme_for(theme))
