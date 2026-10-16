"""Carrega arquivos .ui. Ids ausentes (layout editado) viram widgets descartáveis, para que
remover um elemento do .ui não quebre o app."""

from __future__ import annotations

from gi.repository import Gtk

from .. import GETTEXT_DOMAIN
from ..paths import ui_file


class Ui:
    def __init__(self, name: str) -> None:
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(GETTEXT_DOMAIN)
        self.builder.add_from_file(ui_file(name))
        self.missing: list[str] = []

    def get(self, object_id: str, fallback_type=Gtk.Box):
        obj = self.builder.get_object(object_id)
        if obj is None:
            self.missing.append(object_id)
            obj = fallback_type()
        return obj

    def maybe(self, object_id: str):
        return self.builder.get_object(object_id)
