"""Controladores das páginas. O layout vem de data/ui/page-*.ui; aqui só há comportamento.

A organização segue o app original (ver docs/DESIGN-REFERENCIA.md). Funções que o modelo do
fone selecionado não suporta ficam escondidas (`set_visible(False)`).
"""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from ..i18n import _
from ..protocol import Cap, NoiseCycle
from ..protocol.messages import BALANCE_CENTER, LINUX_TOUCH_HOLD_OPTIONS, TouchHoldOption
from ..services.config import SYSTEM_EQ_BANDS_HZ, SYSTEM_EQ_GAIN_LIMIT
from ..services.device import CommandError
from ..services.profiles import Profile, ProfileError, profile_from_current
from .builder import Ui
from .labels import connection_labels, fit_label, noise_labels, preset_labels, touch_hold_labels

_DEBOUNCE_MS = 300
_NOISE_NAMES = {0: "off", 2: "ambient", 1: "anc"}  # ordem do app original: Desativado · Ambiente · ANC


class Page:
    file = ""

    def __init__(self, window, ui: Ui) -> None:
        self.window = window
        self.app = window.app
        self.device = window.app.device  # proxy do fone selecionado
        self.ui = ui
        self.updating = False
        self.page = ui.get("page", Adw.NavigationPage)

    def run(self, action, *args) -> None:
        """Executa um comando do fone e mostra o erro num toast."""
        if self.updating:
            return
        try:
            action(*args)
        except (CommandError, ValueError) as exc:
            self.window.toast(str(exc))
            GLib.idle_add(lambda: (self.refresh(), GLib.SOURCE_REMOVE)[1])

    def show_if(self, widget, *caps: Cap) -> None:
        widget.set_visible(any(self.device.has(cap) for cap in caps))

    def ready(self) -> bool:
        return self.device.connected and self.device.state.ready

    def refresh(self) -> None:
        self.guarded(self._refresh)

    def _refresh(self) -> None:
        pass

    def guarded(self, fn) -> None:
        self.updating = True
        try:
            fn()
        finally:
            self.updating = False


def _radio_group(group: Adw.PreferencesGroup, labels: dict[int, str], on_selected) -> dict[int, Gtk.CheckButton]:
    buttons: dict[int, Gtk.CheckButton] = {}
    first = None
    for value, label in labels.items():
        button = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        if first is None:
            first = button
        else:
            button.set_group(first)
        button.connect("toggled", lambda b, v=int(value): b.get_active() and on_selected(v))
        row = Adw.ActionRow(title=label, activatable_widget=button)
        row.add_prefix(button)
        group.add(row)
        buttons[int(value)] = button
    return buttons


def _select_radio(buttons: dict[int, Gtk.CheckButton], value) -> None:
    if value in buttons:
        buttons[value].set_active(True)
    else:
        for button in buttons.values():
            button.set_active(False)


def _string_list(items: list[str]) -> Gtk.StringList:
    return Gtk.StringList.new(items)


class Debounce:
    def __init__(self, delay_ms: int, callback) -> None:
        self.delay_ms = delay_ms
        self.callback = callback
        self._source: int | None = None

    def __call__(self, *args) -> None:
        if self._source is not None:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(self.delay_ms, self._fire, args)

    def _fire(self, args) -> bool:
        self._source = None
        self.callback(*args)
        return GLib.SOURCE_REMOVE


def battery_icon(level: int | None, charging: bool | None) -> str:
    if level is None:
        return "battery-missing-symbolic"
    step = min(100, max(0, int(round(level / 10.0)) * 10))
    if charging:
        return f"battery-level-{step}-charging-symbolic"
    return f"battery-level-{step}-symbolic"


def battery_summary(service) -> str:
    """Texto curto para listas de aparelhos: "E 96% · D 97% · Conectado"."""
    s = service.state
    state = connection_labels()[service.connection.value]
    if service.connected and s.battery_left is not None:
        return _("L {left}% · R {right}%").format(left=s.battery_left, right=s.battery_right) + f" · {state}"
    return state


# ---------------------------------------------------------------------------------- Tela inicial


class HomePage(Page):
    file = "page-home.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.selector = ui.get("device_selector", Gtk.MenuButton)
        self.banner = ui.get("banner", Adw.Banner)
        self.name_label = ui.get("device_name_label", Gtk.Label)
        self.status_label = ui.get("device_status_label", Gtk.Label)
        self.experimental = ui.get("experimental_label", Gtk.Label)
        self.battery_box = ui.get("battery_box", Gtk.Box)
        self.battery = {
            side: (
                ui.get(f"battery_{side}_box", Gtk.Box),
                ui.get(f"battery_{side}_icon", Gtk.Image),
                ui.get(f"battery_{side}_bar", Gtk.LevelBar),
                ui.get(f"battery_{side}_label", Gtk.Label),
            )
            for side in ("left", "right", "case")
        }
        self.noise_group = ui.get("quick_noise_group", Adw.PreferencesGroup)
        self.noise = ui.get("noise_toggle", Adw.ToggleGroup)
        self.noise.connect("notify::active-name", self._on_noise)
        self.touch_switch = ui.get("touch_switch", Gtk.Switch)
        self.touch_switch.connect(
            "notify::active", lambda s, _p: self.run(self.device.set_touch_field, "touch_controls", s.get_active())
        )
        self.rows = {name: ui.get(name, Adw.ActionRow) for name in (
            "sound_row", "touch_row", "connections_row", "advanced_row", "accessibility_row", "find_row",
            "about_row", "linux_audio_row", "profiles_row", "diagnostics_row")}
        self.groups = {name: ui.get(name, Adw.PreferencesGroup) for name in (
            "menu_control_group", "menu_features_group", "accessibility_group", "other_apps_group",
            "earbuds_group", "linux_group")}
        self.quick_profile = ui.get("quick_profile_row", Adw.ComboRow)
        self.quick_profile.connect("notify::selected", self._on_quick_profile)
        self._profile_names: list[str] = []

    def set_profiles(self, names: list[str]) -> None:
        def fill():
            self._profile_names = names
            self.quick_profile.set_model(_string_list(["—", *names]))
            self.quick_profile.set_selected(0)
            self.quick_profile.set_sensitive(bool(names))

        self.guarded(fill)

    def _on_noise(self, group, _pspec) -> None:
        values = {name: value for value, name in _NOISE_NAMES.items()}
        name = group.get_active_name()
        if name in values:
            self.run(self.device.set_noise_control, values[name])

    def _on_quick_profile(self, row, _pspec) -> None:
        if self.updating:
            return
        index = row.get_selected()
        if 1 <= index <= len(self._profile_names):
            self.app.apply_profile_by_name(self._profile_names[index - 1])
            self.guarded(lambda: row.set_selected(0))

    def _refresh(self) -> None:
        d, s = self.device, self.device.state
        model = d.model
        dev = d.device
        name = dev.name if dev else _("No earbuds")
        self.selector.set_label(name)
        self.page.set_title(name)
        self.name_label.set_label(dev.name if dev else _("No earbuds added"))
        state = d.connection.value
        detail = self.window.connection_detail if state != "connected" else ""
        text = connection_labels()[state]
        self.status_label.set_label(f"{text} — {detail}" if detail else text)
        self.experimental.set_visible(dev is not None and not model.validated)
        if dev is not None and not model.supported:
            self.banner.set_title(_("This model uses a different protocol and is not supported"))
            self.banner.set_revealed(True)
        elif dev is not None and not model.validated:
            self.banner.set_title(
                _("Experimental: {model} was not tested on real hardware. Only basic features are on.").format(
                    model=model.name or dev.remote_name)
            )
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        self.show_if(self.battery_box, Cap.BATTERY)
        threshold = self.app.config.battery_low_threshold
        values = {
            "left": (s.battery_left, s.charging_left),
            "right": (s.battery_right, s.charging_right),
            "case": (s.battery_case, s.charging_case),
        }
        for side, (level, charging) in values.items():
            box, icon, bar, label = self.battery[side]
            if not d.connected:
                level = charging = None
            bar.set_value(level or 0)
            label.set_label("—" if level is None else f"{level}%")
            icon.set_from_icon_name(battery_icon(level, charging))
            if level is not None and level <= threshold and not charging:
                box.add_css_class("battery-low")
            else:
                box.remove_css_class("battery-low")

        self.show_if(self.noise_group, Cap.NOISE_CONTROL)
        self.noise.set_active_name(_NOISE_NAMES.get(s.noise_control))
        self.noise_group.set_sensitive(d.connected)
        self.touch_switch.set_active(bool(s.touch and s.touch.touch_controls))
        self.touch_switch.set_sensitive(self.ready() and s.touch is not None)

        caps = {
            "sound_row": (Cap.EQ_PRESETS, Cap.FIT_TEST),
            "touch_row": (Cap.TOUCH_LOCK,),
            "advanced_row": (Cap.AMBIENT_DURING_CALLS, Cap.IN_EAR_DETECTION, Cap.GAME_MODE, Cap.EXTRA_HIGH_AMBIENT),
            "accessibility_row": (Cap.BALANCE, Cap.ANC_WITH_ONE_EARBUD, Cap.AMBIENT_CUSTOMIZATION),
            "find_row": (Cap.FIND_MY_EARBUDS,),
            "about_row": (Cap.DEVICE_INFO, Cap.BATTERY),
        }
        for row, row_caps in caps.items():
            self.show_if(self.rows[row], *row_caps)
        self.rows["connections_row"].set_visible(dev is not None)
        for group in self.groups.values():
            group.set_visible(dev is not None)
        self.groups["accessibility_group"].set_visible(self.rows["accessibility_row"].get_visible())
        self.groups["other_apps_group"].set_visible(self.rows["find_row"].get_visible())
        self.groups["earbuds_group"].set_visible(self.rows["about_row"].get_visible())
        for name in ("sound_row", "touch_row", "advanced_row", "accessibility_row", "find_row"):
            self.rows[name].set_sensitive(d.connected)
        if s.equalizer is not None:
            self.rows["sound_row"].set_subtitle(preset_labels().get(s.equalizer, ""))
        else:
            self.rows["sound_row"].set_subtitle("")


# ---------------------------------------------------------------------------------- Som


class SoundPage(Page):
    """Qualidade e efeitos sonoros: Equalizador, Equalizador do computador e Teste de ajuste."""

    file = "page-sound.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.eq_row = ui.get("eq_row", Adw.ActionRow)
        self.system_eq_row = ui.get("system_eq_row", Adw.ActionRow)
        self.fit_group = ui.get("fit_group", Adw.PreferencesGroup)
        self.fit_result = ui.get("fit_result_row", Adw.ActionRow)
        self.fit_button = ui.get("fit_button", Gtk.Button)
        self.fit_button.connect("clicked", self._on_fit)
        self._fit_running = False
        self.device.connect("fit-result", self._on_fit_result)
        self.app.system_eq.connect("changed", lambda *_: self.refresh())

    def _on_fit(self, _button) -> None:
        if self._fit_running:
            self._fit_running = False
            self.run(self.device.fit_test_cancel)
        else:
            try:
                self.device.fit_test_start()
                self._fit_running = True
                self.fit_result.set_subtitle(_("Testing… keep still"))
            except CommandError as exc:
                self.window.toast(str(exc))
        self.refresh()

    def _on_fit_result(self, _device, left: int, right: int) -> None:
        self._fit_running = False
        self.fit_result.set_subtitle(
            _("Left: {left} · Right: {right}").format(left=fit_label(left), right=fit_label(right))
        )
        self.refresh()

    def _refresh(self) -> None:
        d, s = self.device, self.device.state
        self.show_if(self.eq_row, Cap.EQ_PRESETS)
        self.eq_row.set_subtitle(preset_labels().get(s.equalizer, "") if s.equalizer is not None else "")
        self.eq_row.set_sensitive(d.connected)
        self.system_eq_row.set_visible(self.app.system_eq.available)
        self.system_eq_row.set_subtitle(_("On") if self.app.config.system_eq_enabled else _("Off"))
        self.show_if(self.fit_group, Cap.FIT_TEST)
        self.fit_group.set_sensitive(d.connected)
        self.fit_button.set_label(_("Cancel") if self._fit_running else _("Start"))


class EqualizerPage(Page):
    file = "page-equalizer.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.eq_group = ui.get("eq_group", Adw.PreferencesGroup)
        self.eq_buttons = _radio_group(self.eq_group, preset_labels(), lambda v: self.run(self.device.set_preset, v))

    def _refresh(self) -> None:
        _select_radio(self.eq_buttons, self.device.state.equalizer)
        self.eq_group.set_sensitive(self.device.connected)


class SystemEqPage(Page):
    """Equalizador do computador (extra do Linux)."""

    file = "page-system-eq.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.system_eq = self.app.system_eq
        self.switch = ui.get("system_eq_switch", Adw.SwitchRow)
        self.switch.connect("notify::active", self._on_toggle)
        self.bands_box = ui.get("system_eq_bands", Gtk.Box)
        ui.get("system_eq_reset", Gtk.Button).connect("clicked", self._on_reset)
        self.scales: list[Gtk.Scale] = []
        self.values: list[Gtk.Label] = []
        self._push = Debounce(120, self._send_gains)
        self._build_bands()
        self.system_eq.connect("changed", lambda *_: self.refresh())

    def _build_bands(self) -> None:
        gains = self.app.config.system_eq_gains
        for i, freq in enumerate(SYSTEM_EQ_BANDS_HZ):
            band = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            band.add_css_class("eq-band")
            value = Gtk.Label()
            value.add_css_class("eq-band-value")
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -SYSTEM_EQ_GAIN_LIMIT, SYSTEM_EQ_GAIN_LIMIT, 0.5)
            scale.set_inverted(True)
            scale.set_draw_value(False)
            scale.set_vexpand(True)
            scale.add_mark(0, Gtk.PositionType.LEFT, None)
            scale.set_value(gains[i])
            scale.connect("value-changed", self._on_band)
            label = Gtk.Label(label=f"{freq // 1000}k" if freq >= 1000 else str(freq))
            label.add_css_class("eq-band-label")
            band.append(value)
            band.append(scale)
            band.append(label)
            self.bands_box.append(band)
            self.scales.append(scale)
            self.values.append(value)
        self._update_labels()

    def _update_labels(self) -> None:
        for scale, label in zip(self.scales, self.values):
            label.set_label(f"{scale.get_value():+.1f}")

    def _on_band(self, _scale) -> None:
        self._update_labels()
        if not self.updating:
            self._push()

    def _send_gains(self) -> None:
        gains = [round(s.get_value(), 1) for s in self.scales]
        self.app.config.system_eq_gains = gains
        self.app.save_config()
        self.system_eq.set_gains(gains)

    def _on_reset(self, _button) -> None:
        for scale in self.scales:
            scale.set_value(0.0)

    def _on_toggle(self, row, _pspec) -> None:
        if self.updating:
            return
        self.app.config.system_eq_enabled = row.get_active()
        self.app.save_config()
        self.app.update_system_eq()

    def _refresh(self) -> None:
        self.switch.set_active(self.app.config.system_eq_enabled)
        running = self.system_eq.running
        self.switch.set_subtitle(
            _("Active") if running else (_("Waiting for the earbuds audio output") if self.app.config.system_eq_enabled else "")
        )


# ---------------------------------------------------------------------------------- Toques


class TouchPage(Page):
    file = "page-touch.ui"
    GESTURES = ("tap", "double_tap", "triple_tap", "touch_and_hold", "calls_double_tap", "calls_touch_and_hold")
    BASIC = ("tap", "double_tap", "triple_tap", "touch_and_hold")

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.touch_group = ui.get("touch_group", Adw.PreferencesGroup)
        self.lock = ui.get("touch_lock_row", Adw.SwitchRow)
        self.lock.connect("notify::active", lambda r, _p: self.run(self.device.set_touch_field, "touch_controls", r.get_active()))
        self.gestures_group = ui.get("gestures_group", Adw.PreferencesGroup)
        self.calls_group = ui.get("calls_group", Adw.PreferencesGroup)
        self.hold_row = ui.get("hold_row", Adw.ActionRow)
        self.gestures = {}
        for name in self.GESTURES:
            widget = ui.get(f"gesture_{name}", Adw.SwitchRow)
            widget.connect("notify::active", self._on_gesture, name)
            self.gestures[name] = widget

    def _on_gesture(self, widget, _pspec, name: str) -> None:
        if self.updating:
            return
        settings = self.device.state.touch
        if settings is None:
            return
        new = settings.with_(**{name: widget.get_active()})
        # O app original exige pelo menos um gesto de toque ativo (C0089c, case 10).
        if not any(getattr(new, g) for g in self.BASIC):
            self.window.toast(_("Keep at least one gesture on"))
            self.refresh()
            return
        self.run(self.device.set_touch, new)

    def _refresh(self) -> None:
        d, s = self.device, self.device.state
        touch = s.touch
        self.show_if(self.touch_group, Cap.TOUCH_LOCK)
        self.show_if(self.gestures_group, Cap.TOUCH_LOCK)
        self.show_if(self.calls_group, Cap.TOUCH_FOR_CALLS)
        self.lock.set_active(bool(touch and touch.touch_controls))
        for name, widget in self.gestures.items():
            widget.set_active(bool(touch and getattr(touch, name)))
        ready = d.connected and touch is not None
        self.touch_group.set_sensitive(ready)
        for group in (self.gestures_group, self.calls_group):
            group.set_sensitive(ready and touch.touch_controls)
        labels = touch_hold_labels()
        if s.touch_hold_left is not None:
            self.hold_row.set_subtitle(
                _("Left: {left} · Right: {right}").format(
                    left=labels.get(s.touch_hold_left, s.touch_hold_left),
                    right=labels.get(s.touch_hold_right, s.touch_hold_right),
                )
            )
        self.hold_row.set_activatable(self.device.has(Cap.TOUCH_HOLD_OPTION))


class TouchHoldPage(Page):
    """Manter pressionado: opção de cada lado e ciclo de modos de ruído."""

    file = "page-touch-hold.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        labels = touch_hold_labels()
        self.groups = {"left": ui.get("hold_left_group", Adw.PreferencesGroup),
                       "right": ui.get("hold_right_group", Adw.PreferencesGroup)}
        self.buttons: dict[str, dict[int, Gtk.CheckButton]] = {}
        self._other_rows: dict[str, Adw.ActionRow] = {}
        for side, group in self.groups.items():
            options = {int(o): labels[o] for o in LINUX_TOUCH_HOLD_OPTIONS}
            if side == "left":
                options[TouchHoldOption.VOLUME] = _("Volume down")
            else:
                options[TouchHoldOption.VOLUME] = _("Volume up")
            self.buttons[side] = _radio_group(group, options, lambda v, sd=side: self._on_hold(sd, v))
            other = Adw.ActionRow()
            other.add_css_class("dim-label")
            other.set_visible(False)
            group.add(other)
            self._other_rows[side] = other
        self.cycle_group = ui.get("cycle_group", Adw.PreferencesGroup)
        self.cycle_rows = {key: ui.get(f"cycle_{key}", Adw.SwitchRow) for key in ("anc", "ambient", "off")}
        for row in self.cycle_rows.values():
            row.connect("notify::active", self._on_cycle)

    def _on_hold(self, side: str, chosen: int) -> None:
        if self.updating:
            return
        s = self.device.state
        left, right = s.touch_hold_left or chosen, s.touch_hold_right or chosen
        other_value = right if side == "left" else left
        if chosen == TouchHoldOption.VOLUME:
            left = right = TouchHoldOption.VOLUME  # volume vale para os dois lados
        else:
            if side == "left":
                left = chosen
            else:
                right = chosen
            if other_value == TouchHoldOption.VOLUME:
                left = right = chosen  # o app original troca o outro lado junto
        self.run(self.device.set_touch_hold_options, left, right)

    def _on_cycle(self, _row, _pspec) -> None:
        if self.updating:
            return
        cycle = NoiseCycle(*(self.cycle_rows[k].get_active() for k in ("anc", "ambient", "off")))
        if not cycle.valid():
            self.window.toast(_("Choose at least two modes"))
            self.refresh()
            return
        self.run(self.device.set_noise_cycle, cycle, cycle)

    def _refresh(self) -> None:
        d, s = self.device, self.device.state
        labels = touch_hold_labels()
        for side in ("left", "right"):
            current = s.touch_hold_left if side == "left" else s.touch_hold_right
            _select_radio(self.buttons[side], current)
            other = self._other_rows[side]
            other.set_visible(current is not None and current not in self.buttons[side])
            if other.get_visible():
                other.set_title(labels.get(current, _("Other ({value})").format(value=current)))
            self.groups[side].set_sensitive(d.connected and current is not None)
        self.show_if(self.cycle_group, Cap.NOISE_CYCLE)
        cycle = s.noise_cycle_first
        for key, row in self.cycle_rows.items():
            row.set_active(bool(cycle and getattr(cycle, key)))
        uses_noise = TouchHoldOption.NOISE_CONTROLS in (s.touch_hold_left, s.touch_hold_right)
        self.cycle_group.set_sensitive(d.connected and cycle is not None and uses_noise)


# ---------------------------------------------------------------------------------- Conexões


class ConnectionsPage(Page):
    file = "page-connections.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.row = ui.get("connection_row", Adw.ActionRow)
        self.button = ui.get("connect_button", Gtk.Button)
        self.button.connect("clicked", self._on_connect)
        self.reconnect = ui.get("reconnect_row", Adw.SwitchRow)
        self.reconnect.set_active(self.app.config.auto_reconnect)
        self.reconnect.connect("notify::active", self._on_reconnect)
        ui.get("forget_row", Adw.ButtonRow).connect("activated", lambda *_: self.app.confirm_forget_selected())

    def _on_connect(self, _button) -> None:
        if self.device.connection.value == "disconnected":
            self.app.connect_selected()
        else:
            self.device.disconnect_device()

    def _on_reconnect(self, row, _pspec) -> None:
        if self.updating:
            return
        self.app.config.auto_reconnect = row.get_active()
        self.app.save_config()
        self.app.set_auto_reconnect(row.get_active())

    def _refresh(self) -> None:
        state = self.device.connection.value
        detail = self.window.connection_detail if state != "connected" else ""
        text = connection_labels()[state]
        self.row.set_subtitle(f"{text} — {detail}" if detail else text)
        self.button.set_label(_("Connect") if state == "disconnected" else _("Disconnect"))
        self.button.set_sensitive(self.device.device is not None)
        self.reconnect.set_active(self.app.config.auto_reconnect)


# ---------------------------------------------------------------------------------- Recursos avançados, Labs, Acessibilidade


class AdvancedPage(Page):
    file = "page-advanced.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.ambient_calls = ui.get("ambient_calls_row", Adw.SwitchRow)
        self.ambient_calls.connect("notify::active", lambda r, _p: self.run(self.device.set_ambient_during_calls, r.get_active()))
        self.in_ear = ui.get("in_ear_row", Adw.SwitchRow)
        self.in_ear.connect("notify::active", lambda r, _p: self.run(self.device.set_in_ear_detection, r.get_active()))
        self.group = ui.get("advanced_group", Adw.PreferencesGroup)
        self.labs_group = ui.get("labs_group", Adw.PreferencesGroup)

    def _refresh(self) -> None:
        s = self.device.state
        self.show_if(self.ambient_calls, Cap.AMBIENT_DURING_CALLS)
        self.show_if(self.in_ear, Cap.IN_EAR_DETECTION)
        self.show_if(self.group, Cap.AMBIENT_DURING_CALLS, Cap.IN_EAR_DETECTION)
        self.show_if(self.labs_group, Cap.GAME_MODE, Cap.EXTRA_HIGH_AMBIENT, Cap.BALANCE)
        self.ambient_calls.set_active(bool(s.ambient_during_calls))
        self.in_ear.set_active(bool(s.in_ear_detection))
        self.group.set_sensitive(self.ready())


class LabsPage(Page):
    file = "page-labs.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.game_group = ui.get("game_group", Adw.PreferencesGroup)
        self.game = ui.get("game_mode_row", Adw.SwitchRow)
        self.game.connect("notify::active", lambda r, _p: self.run(self.device.set_game_mode, r.get_active()))
        self.extra_group = ui.get("extra_group", Adw.PreferencesGroup)
        self.extra = ui.get("extra_high_row", Adw.SwitchRow)
        self.extra.connect("notify::active", lambda r, _p: self.run(self.device.set_extra_high_ambient, r.get_active()))
        self.hearing_group = ui.get("hearing_group", Adw.PreferencesGroup)

    def _refresh(self) -> None:
        s = self.device.state
        self.show_if(self.game, Cap.GAME_MODE)
        self.show_if(self.extra_group, Cap.EXTRA_HIGH_AMBIENT)
        self.show_if(self.hearing_group, Cap.BALANCE, Cap.ANC_WITH_ONE_EARBUD, Cap.AMBIENT_CUSTOMIZATION)
        self.game.set_active(bool(s.game_mode))
        self.extra.set_active(bool(s.extra_high_ambient))
        for group in (self.game_group, self.extra_group):
            group.set_sensitive(self.ready())


class AccessibilityPage(Page):
    """Acessibilidade / Melhorias de audição: balanço, ruído com um fone, volume do ambiente."""

    file = "page-accessibility.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.balance_group = ui.get("balance_group", Adw.PreferencesGroup)
        self.balance = ui.get("balance_scale", Gtk.Scale)
        send_balance = Debounce(_DEBOUNCE_MS, lambda v: self.run(self.device.set_balance, v))
        self.balance.connect("value-changed", lambda s: None if self.updating else send_balance(int(round(s.get_value()))))
        self.options_group = ui.get("noise_options_group", Adw.PreferencesGroup)
        self.anc_one = ui.get("anc_one_earbud_row", Adw.SwitchRow)
        self.anc_one.connect("notify::active", lambda r, _p: self.run(self.device.set_anc_with_one_earbud, r.get_active()))
        self.ambient_group = ui.get("ambient_group", Adw.PreferencesGroup)
        self.ambient_left = ui.get("ambient_left_scale", Gtk.Scale)
        self.ambient_right = ui.get("ambient_right_scale", Gtk.Scale)
        send = Debounce(_DEBOUNCE_MS, self._send_ambient)
        for scale in (self.ambient_left, self.ambient_right):
            scale.connect("value-changed", lambda _s: None if self.updating else send())

    def _send_ambient(self) -> None:
        self.run(self.device.set_ambient_volume,
                 int(round(self.ambient_left.get_value())), int(round(self.ambient_right.get_value())))

    def _refresh(self) -> None:
        d, s = self.device, self.device.state
        self.show_if(self.balance_group, Cap.BALANCE)
        self.balance_group.set_sensitive(d.connected and s.balance is not None)
        self.balance.set_value(BALANCE_CENTER if s.balance is None else s.balance)
        self.show_if(self.options_group, Cap.ANC_WITH_ONE_EARBUD)
        self.anc_one.set_active(bool(s.anc_with_one_earbud))
        self.show_if(self.ambient_group, Cap.AMBIENT_CUSTOMIZATION)
        extra = bool(s.extra_high_ambient)
        if s.ambient is not None and not extra:
            self.ambient_left.set_value(s.ambient.volume_left)
            self.ambient_right.set_value(s.ambient.volume_right)
        for scale in (self.ambient_left, self.ambient_right):
            scale.set_sensitive(not extra)
        for group in (self.options_group, self.ambient_group):
            group.set_sensitive(self.ready())


# ---------------------------------------------------------------------------------- Buscar, Sobre


class FindPage(Page):
    file = "page-find.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.group = ui.get("find_group", Adw.PreferencesGroup)
        self.button = ui.get("find_button", Gtk.Button)
        self.button.connect("clicked", self._on_find)
        self.mute_left = ui.get("mute_left_row", Adw.SwitchRow)
        self.mute_right = ui.get("mute_right_row", Adw.SwitchRow)
        for row in (self.mute_left, self.mute_right):
            row.connect("notify::active", self._on_mute)
        self.device.connect("find-changed", lambda *_: self.refresh())

    def _on_find(self, _button) -> None:
        if self.device.finding:
            self.run(self.device.find_stop)
        else:
            self.run(self.device.find_start)

    def _on_mute(self, _row, _pspec) -> None:
        self.run(self.device.set_find_mute, self.mute_left.get_active(), self.mute_right.get_active())

    def _refresh(self) -> None:
        d = self.device
        self.group.set_sensitive(d.connected)
        self.button.set_label(_("Stop") if d.finding else _("Start"))
        for cls_on, cls_off in (("destructive-action", "suggested-action"),):
            if d.finding:
                self.button.remove_css_class(cls_off)
                self.button.add_css_class(cls_on)
            else:
                self.button.remove_css_class(cls_on)
                self.button.add_css_class(cls_off)
        for row, muted in ((self.mute_left, d.mute_left), (self.mute_right, d.mute_right)):
            row.set_active(muted)
            row.set_sensitive(d.finding)


class AboutPage(Page):
    file = "page-about.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.device.connect("info-changed", lambda *_: self.refresh())

    def _refresh(self) -> None:
        d = self.device
        info, dev = d.info, d.device
        values = {
            "info_name": dev.name if dev else None,
            "info_model": d.model.name or (dev.remote_name if dev else None),
            "info_serial_left": info.serial_left,
            "info_serial_right": info.serial_right,
            "info_case_serial": info.case_serial,
            "info_fw_left": info.firmware_left,
            "info_fw_right": info.firmware_right,
            "info_case_fw": info.case_firmware,
            "info_address": dev.address if dev else None,
            "info_hw": None if info.hw_left is None else "0x%02X / 0x%02X" % (info.hw_left, info.hw_right),
        }
        for key, value in values.items():
            self.ui.get(key, Adw.ActionRow).set_subtitle(GLib.markup_escape_text(value) if value else "—")


# ---------------------------------------------------------------------------------- Recursos do Linux


class LinuxAudioPage(Page):
    """Áudio Bluetooth: usar como saída, modo A2DP/HFP, codec e troca automática."""

    file = "page-linux-audio.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.audio = self.app.audio
        self.output_row = ui.get("output_row", Adw.ActionRow)
        self.output_button = ui.get("output_button", Gtk.Button)
        self.output_button.connect("clicked", self._on_output)
        self.audio_group = ui.get("audio_group", Adw.PreferencesGroup)
        self.mode = ui.get("audio_mode_row", Adw.ComboRow)
        self.mode.set_model(_string_list([_("Music (A2DP)"), _("Headset with microphone (HFP)")]))
        self.mode.connect("notify::selected", self._on_mode)
        self.codec_row = ui.get("codec_row", Adw.ActionRow)
        self.autoswitch = ui.get("autoswitch_row", Adw.SwitchRow)
        self.autoswitch.set_active(self.app.config.audio_autoswitch)
        self.autoswitch.connect("notify::active", self._on_autoswitch)
        self.audio.connect("changed", lambda *_: self.refresh())
        self._is_default = False

    def _on_output(self, _button) -> None:
        dev = self.device.device
        if dev is None:
            return
        self.output_button.set_sensitive(False)

        def done(error):
            self.output_button.set_sensitive(True)
            if error:
                self.window.toast(_("Could not use the earbuds as audio output: {error}").format(error=error))
            else:
                self.window.toast(_("Sound now plays through {name}").format(name=dev.name))
            self.audio.refresh()

        self.audio.use_as_output(dev.path, done)

    def _on_mode(self, row, _pspec) -> None:
        if not self.updating:
            self.audio.set_kind("a2dp" if row.get_selected() == 0 else "hfp")

    def _on_autoswitch(self, row, _pspec) -> None:
        self.app.config.audio_autoswitch = row.get_active()
        self.app.save_config()
        self.audio.set_autoswitch(row.get_active())

    def _refresh(self) -> None:
        card = self.audio.card
        self.output_row.set_visible(self.audio.available and self.device.device is not None)
        self.audio_group.set_visible(self.audio.available and card is not None)
        if card is not None:
            current = card.current.kind if card.current else None
            self.mode.set_selected(1 if current == "hfp" else 0)
            codec = (card.codec or "").upper()
            self.codec_row.set_subtitle(codec or (card.current.description if card.current else "—"))

        def got(is_default: bool) -> None:
            self.output_row.set_subtitle(
                _("These earbuds are the audio output") if is_default else _("Send the computer sound to these earbuds"))
            self.output_button.set_label(_("In use") if is_default else _("Use"))
            self.output_button.set_sensitive(not is_default)

        self.audio.is_default_output(got)


class ProfilesPage(Page):
    file = "page-profiles.ui"

    def __init__(self, window, ui: Ui) -> None:
        super().__init__(window, ui)
        self.group = ui.get("profiles_group", Adw.PreferencesGroup)
        self.empty_row = ui.get("profiles_empty_row", Adw.ActionRow)
        self.entry = ui.get("new_profile_entry", Adw.EntryRow)
        self.entry.connect("apply", self._on_save)
        ui.get("import_button", Gtk.Button).connect("clicked", self._on_import)
        ui.get("export_button", Gtk.Button).connect("clicked", self._on_export)
        self.rows: list[Adw.ActionRow] = []

    def _on_save(self, entry) -> None:
        name = entry.get_text().strip()
        if not name:
            return
        if not self.device.connected:
            self.window.toast(_("Connect the earbuds to save their current settings"))
            return
        try:
            self.app.profiles.put(profile_from_current(name, self.device, self.app.config))
        except ProfileError as exc:
            self.window.toast(str(exc))
            return
        entry.set_text("")
        self.window.toast(_("Profile “{name}” saved").format(name=name))
        self.app.profiles_changed()

    def _summary(self, p: Profile) -> str:
        parts = []
        if p.preset is not None:
            parts.append(preset_labels().get(p.preset, "?"))
        if p.noise_control is not None:
            parts.append(noise_labels().get(p.noise_control, "?"))
        if p.system_eq_enabled:
            parts.append(_("Computer equalizer"))
        return " · ".join(parts)

    def rebuild(self) -> None:
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        profiles = self.app.profiles.profiles
        self.empty_row.set_visible(not profiles)
        for profile in profiles:
            row = Adw.ActionRow(title=GLib.markup_escape_text(profile.name), subtitle=self._summary(profile))
            apply = Gtk.Button(label=_("Apply"), valign=Gtk.Align.CENTER)
            apply.add_css_class("suggested-action")
            apply.connect("clicked", lambda _b, n=profile.name: self.app.apply_profile_by_name(n))
            delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text=_("Delete"))
            delete.add_css_class("flat")
            delete.connect("clicked", lambda _b, n=profile.name: self._delete(n))
            row.add_suffix(apply)
            row.add_suffix(delete)
            self.group.add(row)
            self.rows.append(row)

    def _delete(self, name: str) -> None:
        self.app.profiles.delete(name)
        self.app.profiles_changed()
        self.window.toast(_("Profile “{name}” deleted").format(name=name))

    def _json_filter(self) -> Gio.ListStore:
        flt = Gtk.FileFilter()
        flt.set_name(_("Buds Studio profiles (JSON)"))
        flt.add_suffix("json")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        return store

    def _on_export(self, _button) -> None:
        if not self.app.profiles.profiles:
            self.window.toast(_("There are no profiles to export"))
            return
        dialog = Gtk.FileDialog(title=_("Export profiles"), initial_name="buds-studio-profiles.json")
        dialog.set_filters(self._json_filter())

        def done(d, result):
            try:
                file = d.save_finish(result)
            except GLib.Error:
                return
            try:
                self.app.profiles.export(file.get_path())
                self.window.toast(_("Profiles exported"))
            except OSError as exc:
                self.window.toast(str(exc))

        dialog.save(self.window.window, None, done)

    def _on_import(self, _button) -> None:
        dialog = Gtk.FileDialog(title=_("Import profiles"))
        dialog.set_filters(self._json_filter())

        def done(d, result):
            try:
                file = d.open_finish(result)
            except GLib.Error:
                return
            try:
                names = self.app.profiles.import_file(file.get_path())
            except ProfileError as exc:
                self.window.toast(str(exc))
                return
            self.app.profiles_changed()
            self.window.toast(_("{count} profile(s) imported").format(count=len(names)))

        dialog.open(self.window.window, None, done)


PAGES = (
    HomePage, SoundPage, EqualizerPage, SystemEqPage, TouchPage, TouchHoldPage, ConnectionsPage,
    AdvancedPage, LabsPage, AccessibilityPage, FindPage, AboutPage, LinuxAudioPage, ProfilesPage,
)
