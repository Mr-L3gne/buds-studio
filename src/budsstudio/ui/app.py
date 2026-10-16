"""Aplicativo: liga serviços, janela, bandeja, notificações e CLI."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, APP_NAME, VERSION  # noqa: E402
from ..cli import CliError, build_parser, is_action  # noqa: E402
from ..cli.runner import CliRunner  # noqa: E402
from ..i18n import _  # noqa: E402
from ..protocol import Cap, MsgId  # noqa: E402
from ..services import background  # noqa: E402
from ..services.audio import AudioService  # noqa: E402
from ..services.config import Config  # noqa: E402
from ..services.device import CommandError  # noqa: E402
from ..services.manager import DeviceManager, SelectedDevice  # noqa: E402
from ..services.notifications import NotificationService  # noqa: E402
from ..services.profiles import ProfileStore, apply_profile  # noqa: E402
from ..services.system_eq import SystemEqService  # noqa: E402
from ..services.tray import MenuItem, TrayIcon  # noqa: E402
from ..transport.bluez import BluezError  # noqa: E402
from .labels import connection_labels, noise_labels, preset_labels  # noqa: E402


CLI_INTERFACE = "io.github.mr_l3gne.BudsStudio.Cli"
CLI_PATH = "/io/github/mr_l3gne/BudsStudio/Cli"
_CLI_XML = f"""
<node>
  <interface name="{CLI_INTERFACE}">
    <method name="Run">
      <arg type="as" name="argv" direction="in"/>
      <arg type="i" name="status" direction="out"/>
      <arg type="s" name="stdout" direction="out"/>
      <arg type="s" name="stderr" direction="out"/>
    </method>
  </interface>
</node>
"""


class BudsStudioApplication(Adw.Application):
    def __init__(self, config: Config) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.config = config
        self.window = None
        self.devices = []
        self.persistent = False  # janela aberta ou modo bandeja (não é só um comando da CLI)
        self.device: SelectedDevice | None = None
        self.tray: TrayIcon | None = None
        self._started = False
        self._background_hold = False
        self._pending_cli: list = []
        self._cli_running = 0
        self.exit_code = 0

    # Inicialização

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        from .style import apply_theme

        apply_theme(self.config.theme)
        self.manager = DeviceManager(auto_reconnect=self.config.auto_reconnect)
        self.manager.on_service_created = self._on_service_created
        self.device = SelectedDevice(self.manager)  # o fone escolhido, para a interface e a CLI
        self.audio = AudioService()
        self.system_eq = SystemEqService(_("Buds Studio EQ"))
        self.system_eq.set_gains(self.config.system_eq_gains)
        self.profiles = ProfileStore()
        self._notifications: dict[str, NotificationService] = {}

        self.manager.connect("devices-changed", lambda *_: self._on_devices_changed())
        self.manager.connect("selected-changed", lambda *_: self._on_selected_changed())
        self.manager.connect("device-updated", lambda _m, address: self._on_device_updated(address))
        self.device.connect("connection-changed", self._on_connection_changed)
        self.device.connect("state-changed", lambda *_: self._on_state_changed())
        self.audio.connect("changed", self._on_audio_changed)
        self.audio.connect("error", lambda _a, msg: self.toast(_("Could not change the audio mode: {error}").format(error=msg)))
        self.system_eq.connect("error", lambda _s, msg: self.toast(_("System equalizer error: {error}").format(error=msg)))
        self.audio.set_autoswitch(self.config.audio_autoswitch)

        for name, callback in (
            ("about", self._on_about),
            ("preferences", lambda *_: self.show_preferences()),
            ("quit", lambda *_: self.quit()),
            ("show", lambda *_: self.show_window()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("app.preferences", ["<Control>comma"])
        self._register_cli_object()

    def _register_cli_object(self) -> None:
        """Objeto D-Bus para a CLI de uma segunda instância. No Flatpak o proxy de D-Bus não deixa
        a instância principal chamar a segunda (o que o GApplicationCommandLine faz para imprimir),
        então a segunda chama `Run` aqui e recebe a saída na resposta."""
        connection = self.get_dbus_connection()
        if connection is None:
            return
        info = Gio.DBusNodeInfo.new_for_xml(_CLI_XML).interfaces[0]
        try:
            connection.register_object(CLI_PATH, info, self._on_cli_call, None, None)
        except GLib.Error:
            pass

    def _on_cli_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        if method != "Run":
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
            return
        (argv,) = params.unpack()
        out_lines: list[str] = []
        err_lines: list[str] = []

        def finish(code: int) -> None:
            invocation.return_value(GLib.Variant("(iss)", (code, "\n".join(out_lines), "\n".join(err_lines))))

        self.run_cli(list(argv), out_lines.append, err_lines.append, finish)

    def do_shutdown(self) -> None:
        if self.device is not None:
            self.manager.shutdown()
            self.system_eq.shutdown()
            self.audio.shutdown()
        if self.tray is not None:
            self.tray.stop()
        Adw.Application.do_shutdown(self)

    def do_command_line(self, cmdline: Gio.ApplicationCommandLine) -> int:
        argv = cmdline.get_arguments()[1:]

        def out(text: str) -> None:
            cmdline.print_literal(text + "\n")

        def err(text: str) -> None:
            cmdline.printerr_literal(text + "\n")

        def finish(code: int) -> None:
            cmdline.set_exit_status(code)
            if not cmdline.get_is_remote():
                self.exit_code = code  # GApplication.run() ignora set_exit_status localmente
            if hasattr(cmdline, "done"):
                cmdline.done()

        self._pending_cli.append(cmdline)  # mantém o objeto vivo até o fim
        self.run_cli(argv, out, err, lambda code: (finish(code), self._pending_cli.remove(cmdline)))
        return 0

    def run_cli(self, argv: list[str], out, err, finish) -> None:
        """Interpreta os argumentos: abre a janela, entra em segundo plano ou roda um comando."""
        parser = build_parser()
        try:
            args = parser.parse_args(argv)
        except CliError as exc:
            err(str(exc))
            return finish(2)
        if args.help:
            out(parser.format_help())
            return finish(0)
        if args.version:
            out(f"{APP_NAME} {VERSION}")
            return finish(0)
        if not is_action(args):
            if args.background:
                self._start_background()
            else:
                self.activate()
            return finish(0)

        self.hold()
        self._cli_running += 1

        def done(code: int) -> None:
            self._cli_running -= 1
            finish(code)
            if not self.persistent and self._cli_running == 0:
                self.manager.shutdown()
            self.release()

        CliRunner(self, args, out, err, done).start()

    def do_activate(self) -> None:
        self.show_window()

    def show_window(self) -> None:
        from .style import load_stylesheet
        from .window import MainWindow

        self.persistent = True
        self.start_device()
        if self.window is None:
            load_stylesheet()
            self.window = MainWindow(self)
            self.window.connection_changed(self.device.connection.value, "")
        self.window.present()
        self.update_tray()

    def _start_background(self) -> None:
        self.persistent = True
        if not self._background_hold:
            self._background_hold = True
            self.hold()  # mantém o app vivo sem janela
        self.update_tray()
        self.start_device()

    def keep_running_in_background(self) -> bool:
        if self.tray is not None and self.tray.registered:
            if not self._background_hold:
                self._background_hold = True
                self.hold()
            return True
        return False

    # Fones

    def list_devices(self):
        """Fones compatíveis pareados no BlueZ."""
        try:
            self.devices = self.manager.paired()
        except BluezError as exc:
            self.devices = []
            self.toast(str(exc))
            raise
        return self.devices

    def refresh_devices(self) -> None:
        try:
            self.list_devices()
        except BluezError:
            return
        # Atualiza nome/apelido dos fones já adicionados.
        for dev in self.devices:
            service = self.manager.get(dev.address)
            if service is not None:
                service.device = dev
        if self.window is not None:
            self.window.devices_changed()

    def find_device(self, query: str):
        """Fone pareado por endereço ou nome (para --device)."""
        service = self.manager.find(query)
        if service is not None and service.device is not None:
            return service.device
        try:
            devices = self.list_devices()
        except BluezError:
            return None
        q = query.strip().casefold()
        return next((d for d in devices if q in (d.address.casefold(), d.name.casefold(), d.remote_name.casefold())), None)

    def start_device(self) -> None:
        """Na primeira vez: conecta os fones adicionados ao app (ou o primeiro pareado)."""
        if self._started:
            return
        self._started = True
        try:
            self.list_devices()
        except BluezError:
            return
        by_address = {d.address.upper(): d for d in self.devices}
        known = [a.upper() for a in self.config.devices if a.upper() in by_address]
        if not known and self.devices:
            known = [self.devices[0].address.upper()]
            self.config.devices = known
            self.save_config()
        for address in known:
            self._add(by_address[address])
        if self.config.last_device and self.config.last_device.upper() in self.manager.services:
            self.manager.select(self.config.last_device)

    def _add(self, device, connect: bool = True):
        try:
            return self.manager.add(device, connect=connect)
        except BluezError as exc:
            self.toast(str(exc))
            return self.manager.get(device.address)

    def add_device(self, device) -> None:
        """Adiciona um fone pareado ao app, conecta e seleciona."""
        self._add(device)
        address = device.address.upper()
        if address not in [a.upper() for a in self.config.devices]:
            self.config.devices.append(address)
            self.save_config()
        self.manager.select(address)

    def forget_device(self, address: str) -> None:
        self.manager.forget(address)
        self.config.devices = [a for a in self.config.devices if a.upper() != address.upper()]
        self.config.device_presets.pop(address.upper(), None)
        if self.config.last_device and self.config.last_device.upper() == address.upper():
            self.config.last_device = self.manager.selected_address
        self.save_config()

    def connect_selected(self) -> None:
        service = self.manager.selected
        if service.device is not None:
            try:
                service.connect_device(service.device)
            except BluezError as exc:
                self.toast(str(exc))

    def connect_device_for_cli(self, device, channel) -> None:
        if device is None:
            self.start_device()
            service = self.manager.selected
            if service.device is None:
                raise CliError(_("No paired compatible earbuds"))
            if channel is None and service.connection.value in ("connecting", "connected", "waiting"):
                return  # start_device já está conectando: não reinicia a conexão
            device = service.device
        service = self._add(device, connect=False)
        self.manager.select(device.address)
        service.connect_device(device, channel)

    def set_auto_reconnect(self, enabled: bool) -> None:
        self.manager.auto_reconnect = enabled
        for service in self.manager.services.values():
            service.transport.auto_reconnect = enabled

    def _on_service_created(self, service) -> None:
        if service.device is not None:
            self._notifications[service.device.address.upper()] = NotificationService(self, service, self.config)
        service.connect("ready", self._on_ready)
        service.connect("ack", self._on_ack)

    def _on_devices_changed(self) -> None:
        for address in list(self._notifications):
            if address not in self.manager.services:
                self._notifications.pop(address)
        if self.window is not None:
            self.window.devices_changed()
        self._update_tray_menu()

    def _on_selected_changed(self) -> None:
        address = self.manager.selected_address
        self.audio.set_address(address)
        if address and self.config.last_device != address:
            self.config.last_device = address
            self.save_config()
        if self.window is not None:
            self.window.selection_changed()
        self._update_tray_menu()

    def _on_device_updated(self, address: str) -> None:
        if self.window is not None:
            self.window.device_updated(address)
        self._update_tray_menu()

    def _on_connection_changed(self, _device, state: str, detail: str) -> None:
        if self.window is not None:
            self.window.connection_changed(state, detail)
        if state == "connected":
            self.audio.refresh()

    def _on_state_changed(self) -> None:
        if self.window is not None:
            self.window.refresh()

    def _on_ready(self, service) -> None:
        if service.device is None:
            return
        preset = self.config.device_presets.get(service.device.address.upper())
        if self.config.reapply_preset_on_connect and preset is not None and service.state.equalizer != preset:
            try:
                service.set_preset(preset)
            except CommandError:
                pass

    def _on_ack(self, service, msg_id: int) -> None:
        if msg_id != MsgId.EQUALIZER or service.device is None or service.state.equalizer is None:
            return
        address = service.device.address.upper()
        if self.config.device_presets.get(address) != service.state.equalizer:
            self.config.device_presets[address] = int(service.state.equalizer)
            self.save_config()

    def show_add_device(self) -> None:
        self.show_window()
        try:
            paired = self.list_devices()
        except BluezError:
            return
        candidates = [d for d in paired if d.address.upper() not in self.manager.services]
        dialog = Adw.AlertDialog(heading=_("Add new device"))
        if not candidates:
            dialog.set_body(_("All paired compatible earbuds are already in Buds Studio. Pair new earbuds in the system Bluetooth settings first."))
        else:
            dialog.set_body(_("Choose earbuds already paired with this computer."))
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listbox.add_css_class("boxed-list")
            for dev in candidates:
                row = Adw.ActionRow(title=GLib.markup_escape_text(dev.name), subtitle=dev.address, activatable=True)
                row.add_suffix(Gtk.Image(icon_name="list-add-symbolic"))
                listbox.append(row)

            def chosen(_lb, row):
                dialog.close()
                self.add_device(candidates[row.get_index()])

            listbox.connect("row-activated", chosen)
            dialog.set_extra_child(listbox)
        dialog.add_response("close", _("Close"))
        dialog.present(self.window.window)

    def confirm_forget_selected(self) -> None:
        service = self.manager.selected
        if service.device is None:
            return
        self.show_window()
        address = service.device.address
        dialog = Adw.AlertDialog(
            heading=_("Remove {name}?").format(name=service.device.name),
            body=_("Buds Studio disconnects and forgets these earbuds. They stay paired with this computer."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, r: r == "remove" and self.forget_device(address))
        dialog.present(self.window.window)

    # Áudio

    def _on_audio_changed(self, _audio) -> None:
        card = self.audio.card
        self.system_eq.set_target_sink(card.sink_node if card else None)
        self.update_system_eq()

    def update_system_eq(self) -> None:
        if not self.persistent:
            return
        self.system_eq.set_gains(self.config.system_eq_gains)
        self.system_eq.set_enabled(self.config.system_eq_enabled)

    # Perfis

    def profiles_changed(self) -> None:
        if self.window is not None:
            self.window.profiles_changed()
        self._update_tray_menu()

    def apply_profile_by_name(self, name: str) -> None:
        profile = self.profiles.get(name)
        if profile is None:
            return
        if not self.device.connected:
            self.toast(_("Connect the earbuds first"))
            return
        skipped = apply_profile(profile, self.device, self.system_eq)
        if profile.system_eq_enabled is not None:
            self.config.system_eq_enabled = profile.system_eq_enabled
            if profile.system_eq_gains is not None:
                self.config.system_eq_gains = list(profile.system_eq_gains)
            self.save_config()
        message = _("Profile “{name}” applied").format(name=profile.name)
        if skipped:
            message += " — " + _("not applied: {items}").format(items=", ".join(skipped))
        self.toast(message)

    # Bandeja, autostart, preferências

    def update_tray(self) -> None:
        if self.config.tray_icon and self.tray is None:
            self.tray = TrayIcon(self.show_window)
            self.tray.start()
            self._update_tray_menu()
        elif not self.config.tray_icon and self.tray is not None:
            self.tray.stop()
            self.tray = None

    def _update_tray_menu(self) -> None:
        if self.tray is None:
            return
        lines = []
        for service in self.manager.services.values():
            if service.device is None:
                continue
            st = service.state
            if service.connected and st.battery_left is not None:
                text = _("L {left}% · R {right}%").format(left=st.battery_left, right=st.battery_right)
                if st.battery_case is not None:
                    text += " · " + _("case {case}%").format(case=st.battery_case)
            else:
                text = connection_labels()[service.connection.value]
            lines.append(f"{service.device.name}: {text}")
        d, s = self.device, self.device.state
        title = f"{APP_NAME} — {d.device.name}" if d.device else APP_NAME
        items = [MenuItem(line, enabled=False) for line in lines] or [MenuItem(_("No earbuds added"), enabled=False)]
        items += [MenuItem(separator=True), MenuItem(_("Open Buds Studio"), self.show_window)]
        if len(self.manager.services) > 1:
            items.append(MenuItem(_("Devices"), children=[
                MenuItem(svc.device.name if svc.device else addr, (lambda a=addr: self.manager.select(a)),
                         radio=addr == self.manager.selected_address)
                for addr, svc in self.manager.services.items()
            ]))
        if d.connected and d.has(Cap.EQ_PRESETS):
            items.append(MenuItem(_("Equalizer"), children=[
                MenuItem(label, (lambda v=value: self._safe(d.set_preset, v)), radio=s.equalizer == value)
                for value, label in preset_labels().items()
            ]))
        if d.connected and d.has(Cap.NOISE_CONTROL):
            items.append(MenuItem(_("Noise control"), children=[
                MenuItem(label, (lambda v=value: self._safe(d.set_noise_control, v)), radio=s.noise_control == value)
                for value, label in noise_labels().items()
            ]))
        if d.connected and self.profiles.profiles:
            items.append(MenuItem(_("Profiles"), children=[
                MenuItem(p.name, (lambda n=p.name: self.apply_profile_by_name(n))) for p in self.profiles.profiles
            ]))
        items += [MenuItem(separator=True), MenuItem(_("Quit"), self.quit)]
        self.tray.update(title, "\n".join(lines), items)

    def _safe(self, call, *args) -> None:
        try:
            call(*args)
        except CommandError as exc:
            self.toast(str(exc))

    def set_autostart(self, enabled: bool) -> None:
        def done(ok: bool, error: str) -> None:
            if not ok:
                self.config.autostart = not enabled
                self.save_config()
                self.toast(_("Could not change autostart: {error}").format(error=error or _("denied")))

        window = self.window.window if self.window else None
        background.set_autostart(enabled, _("Keep the earbuds settings available"), window, done)

    def save_config(self) -> None:
        try:
            self.config.save()
        except OSError as exc:
            self.toast(_("Could not save preferences: {error}").format(error=exc))

    def apply_background(self) -> None:
        if self.window is not None:
            self.window.apply_background()

    def toast(self, message: str) -> None:
        if self.window is not None:
            self.window.toast(message)

    def show_preferences(self) -> None:
        from .dialogs import PreferencesDialog

        self.show_window()
        PreferencesDialog(self).present(self.window.window)

    def show_diagnostics(self) -> None:
        from .dialogs import DiagnosticsDialog

        self.show_window()
        DiagnosticsDialog(self).present(self.window.window)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Mr-L3gne",
            comments=_("Equalizer and settings for Galaxy Buds on Linux. Independent project, not affiliated with Samsung."),
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self.window.window if self.window else None)


def run(argv: list[str], config: Config) -> int:
    GLib.set_application_name(APP_NAME)
    app = BudsStudioApplication(config)
    status = app.run(argv)
    return app.exit_code or status
