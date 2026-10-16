"""Diálogos: informações do dispositivo, diagnóstico (pacotes em hex) e preferências."""

from __future__ import annotations

import shutil

from gi.repository import Adw, Gio, GLib, Gtk

from ..i18n import _
from ..services.device import format_packet
from .builder import Ui
from .style import THEMES, apply_theme, builtin_backgrounds, resolve_background, user_backgrounds, user_backgrounds_dir


class DiagnosticsDialog:
    def __init__(self, app) -> None:
        self.app = app
        ui = Ui("diagnostics.ui")
        self.dialog = ui.get("dialog", Adw.Dialog)
        self.view = ui.get("log_view", Gtk.TextView)
        self.buffer = self.view.get_buffer()
        self.pause = ui.get("pause_button", Gtk.ToggleButton)
        self.scroller = ui.get("scroller", Gtk.ScrolledWindow)
        ui.get("copy_button", Gtk.Button).connect("clicked", self._copy)
        ui.get("clear_button", Gtk.Button).connect("clicked", self._clear)
        self.buffer.set_text("\n".join(format_packet(p) for p in app.device.packets))
        self._handler = app.device.connect("packet", self._on_packet)
        self.dialog.connect("closed", lambda *_: app.device.disconnect(self._handler))

    def _on_packet(self, _device, packet) -> None:
        if self.pause.get_active():
            return
        end = self.buffer.get_end_iter()
        prefix = "\n" if self.buffer.get_char_count() else ""
        self.buffer.insert(end, prefix + format_packet(packet))
        adj = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), GLib.SOURCE_REMOVE)[1])

    def _copy(self, _button) -> None:
        start, end = self.buffer.get_bounds()
        self.view.get_clipboard().set(self.buffer.get_text(start, end, False))

    def _clear(self, _button) -> None:
        self.app.device.packets.clear()
        self.buffer.set_text("")

    def present(self, parent) -> None:
        self.dialog.present(parent)


class PreferencesDialog:
    LANGUAGES = (("pt_BR", "Português (Brasil)"), ("en", "English"), ("auto", None))

    def __init__(self, app) -> None:
        self.app = app
        self.config = app.config
        self.ui = ui = Ui("preferences.ui")
        self.dialog = ui.get("dialog", Adw.PreferencesDialog)
        self._updating = True

        language = ui.get("language_row", Adw.ComboRow)
        names = [label or _("Automatic (system)") for _code, label in self.LANGUAGES]
        language.set_model(Gtk.StringList.new(names))
        codes = [code for code, _label in self.LANGUAGES]
        language.set_selected(codes.index(self.config.language) if self.config.language in codes else 0)
        language.connect("notify::selected", lambda r, _p: self._set("language", codes[r.get_selected()]))

        theme = ui.get("theme_row", Adw.ComboRow)
        theme.set_model(Gtk.StringList.new([_("Follow system"), _("Light"), _("Dark")]))
        theme.set_selected(THEMES.index(self.config.theme) if self.config.theme in THEMES else 0)
        theme.connect("notify::selected", self._on_theme)

        self._switch("reconnect_row", "auto_reconnect", app.set_auto_reconnect)
        self._switch("reapply_row", "reapply_preset_on_connect")
        self._switch("tray_row", "tray_icon", lambda _v: app.update_tray())
        self._switch("autostart_row", "autostart", self._on_autostart)
        self._switch("notify_connection_row", "notify_connection")
        self._switch("notify_battery_row", "notify_battery")
        threshold = ui.get("battery_threshold_row", Adw.SpinRow)
        threshold.set_value(self.config.battery_low_threshold)
        threshold.connect("notify::value", lambda r, _p: self._set("battery_low_threshold", int(r.get_value())))

        self.background_row = ui.get("background_row", Adw.ComboRow)
        self.background_row.connect("notify::selected", self._on_background)
        ui.get("background_choose_row", Adw.ButtonRow).connect("activated", self._choose_background)
        self._fill_backgrounds()
        self._updating = False

    def _on_theme(self, row, _pspec) -> None:
        if self._updating:
            return
        theme = THEMES[row.get_selected()]
        self.config.theme = theme
        self.app.save_config()
        apply_theme(theme)  # vale na hora

    def _switch(self, row_id: str, key: str, after=None) -> None:
        row = self.ui.get(row_id, Adw.SwitchRow)
        row.set_active(bool(getattr(self.config, key)))

        def changed(r, _p):
            self._set(key, r.get_active())
            if after is not None and not self._updating:
                after(r.get_active())

        row.connect("notify::active", changed)

    def _set(self, key: str, value) -> None:
        if self._updating:
            return
        setattr(self.config, key, value)
        self.app.save_config()
        if key == "language":
            self.app.toast(_("Restart Buds Studio to change the language"))

    def _fill_backgrounds(self) -> None:
        self._background_values = [""]
        names = [_("Neutral (no image)")]
        for path in builtin_backgrounds():
            self._background_values.append(f"builtin:{path.name}")
            names.append(path.stem.replace("-", " ").capitalize())
        for path in user_backgrounds():
            self._background_values.append(f"user:{path.name}")
            names.append(_("My image: {name}").format(name=path.name))
        updating = self._updating
        self._updating = True
        self.background_row.set_model(Gtk.StringList.new(names))
        current = self.config.background if resolve_background(self.config.background) else ""
        self.background_row.set_selected(self._background_values.index(current) if current in self._background_values else 0)
        self._updating = updating

    def _on_background(self, row, _pspec) -> None:
        if self._updating:
            return
        index = row.get_selected()
        if 0 <= index < len(self._background_values):
            self._set("background", self._background_values[index])
            self.app.apply_background()

    def _choose_background(self, _row) -> None:
        flt = Gtk.FileFilter()
        flt.set_name(_("Images"))
        flt.add_pixbuf_formats()
        flt.add_suffix("svg")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dialog = Gtk.FileDialog(title=_("Choose a background image"))
        dialog.set_filters(filters)

        def done(d, result):
            try:
                file = d.open_finish(result)
            except GLib.Error:
                return
            source = file.get_path()
            if not source:
                return
            folder = user_backgrounds_dir()
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / file.get_basename()
            try:
                shutil.copyfile(source, target)
            except OSError as exc:
                self.app.toast(str(exc))
                return
            self.config.background = f"user:{target.name}"
            self.app.save_config()
            self._fill_backgrounds()
            self.app.apply_background()

        dialog.open(self.app.window.window if self.app.window else None, None, done)

    def _on_autostart(self, enabled: bool) -> None:
        self.app.set_autostart(enabled)

    def present(self, parent) -> None:
        self.dialog.present(parent)
