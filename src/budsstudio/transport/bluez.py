"""Acesso ao BlueZ via D-Bus (Gio): fones pareados e perfil RFCOMM (org.bluez.Profile1).

O BlueZ faz a busca SDP do UUID de controle, abre o canal RFCOMM e entrega o fd em
`Profile1.NewConnection`, então o app não precisa conhecer o número do canal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from gi.repository import Gio, GLib

from ..i18n import N_, _

BLUEZ = "org.bluez"
DEVICE_IFACE = "org.bluez.Device1"
PROFILE_MANAGER_IFACE = "org.bluez.ProfileManager1"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# UUID do serviço de controle usado pelo plugin (docs/PROTOCOLO.md §1, `e8.G.<clinit>`).
CONTROL_UUID = "2e73a4ad-332d-41fc-90e2-16bef06523f2"

PROFILE_PATH = "/io/github/mr_l3gne/BudsStudio/profile"

_CONNECT_TIMEOUT_MS = 30_000

_PROFILE_XML = """
<node>
  <interface name="org.bluez.Profile1">
    <method name="Release"/>
    <method name="NewConnection">
      <arg type="o" name="device" direction="in"/>
      <arg type="h" name="fd" direction="in"/>
      <arg type="a{sv}" name="properties" direction="in"/>
    </method>
    <method name="RequestDisconnection">
      <arg type="o" name="device" direction="in"/>
    </method>
  </interface>
</node>
"""


_FRIENDLY_ERRORS = {
    "br-connection-page-timeout": N_("The earbuds did not answer (in the case, off or out of range?)"),
    "br-connection-busy": N_("Bluetooth is busy; try again"),
    "br-connection-profile-unavailable": N_("The earbuds do not offer the control service right now"),
}


class BluezError(Exception):
    pass


@dataclass(frozen=True)
class BluezDevice:
    path: str
    address: str
    name: str  # apelido exibido (Alias)
    connected: bool
    remote_name: str = ""  # nome anunciado pelo fone (Name), usado para detectar o modelo


def _error_text(exc: GLib.Error) -> str:
    remote = Gio.DBusError.get_remote_error(exc)
    message = exc.message
    if remote and message.startswith("GDBus.Error:"):
        message = message.split(": ", 1)[-1]
    if message in _FRIENDLY_ERRORS:
        return _(_FRIENDLY_ERRORS[message])
    return f"{message} ({remote})" if remote else message


def system_bus() -> Gio.DBusConnection:
    try:
        return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as exc:
        raise BluezError(_("System D-Bus unavailable: {error}").format(error=_error_text(exc))) from exc


def list_devices(bus: Gio.DBusConnection) -> list[BluezDevice]:
    """Aparelhos pareados que anunciam o UUID de controle."""
    try:
        reply = bus.call_sync(
            BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
            None, GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 5000, None,
        )
    except GLib.Error as exc:
        raise BluezError(_("BlueZ did not answer: {error}").format(error=_error_text(exc))) from exc
    (objects,) = reply.unpack()
    devices = []
    for path, interfaces in objects.items():
        props = interfaces.get(DEVICE_IFACE)
        if not props or not props.get("Paired"):
            continue
        uuids = [u.lower() for u in props.get("UUIDs", [])]
        if CONTROL_UUID not in uuids:
            continue
        devices.append(
            BluezDevice(
                path=path,
                address=props.get("Address", ""),
                name=props.get("Alias") or props.get("Name") or props.get("Address", ""),
                connected=bool(props.get("Connected")),
                remote_name=props.get("Name") or props.get("Alias") or "",
            )
        )
    return sorted(devices, key=lambda d: (not d.connected, d.name))


class RfcommProfile:
    """Objeto org.bluez.Profile1 registrado como cliente do UUID de controle.

    O BlueZ entrega todas as conexões desse UUID a um único objeto, então ele é compartilhado
    por todos os fones (`shared()`) e repassa cada conexão ao transporte do aparelho certo.
    """

    _instances: dict[int, "RfcommProfile"] = {}

    @classmethod
    def shared(cls, bus: Gio.DBusConnection) -> "RfcommProfile":
        key = id(bus)
        if key not in cls._instances:
            cls._instances[key] = cls(bus)
        return cls._instances[key]

    def __init__(self, bus: Gio.DBusConnection) -> None:
        self._bus = bus
        self._registration = None
        self._registered = False
        self._handlers: dict[str, tuple[Callable[[str, int], None], Callable[[str], None]]] = {}

    def add(self, device_path: str, on_connection, on_disconnect_request) -> None:
        self._handlers[device_path] = (on_connection, on_disconnect_request)
        self.register()

    def remove(self, device_path: str) -> None:
        self._handlers.pop(device_path, None)
        if not self._handlers:
            self.unregister()

    def register(self) -> None:
        if self._registered:
            return
        info = Gio.DBusNodeInfo.new_for_xml(_PROFILE_XML)
        if self._registration is None:
            self._registration = self._bus.register_object(
                PROFILE_PATH, info.interfaces[0], self._on_method_call, None, None
            )
        options = {
            "Name": GLib.Variant("s", "Buds Studio"),
            "Role": GLib.Variant("s", "client"),
            "AutoConnect": GLib.Variant("b", False),
        }
        try:
            self._bus.call_sync(
                BLUEZ, "/org/bluez", PROFILE_MANAGER_IFACE, "RegisterProfile",
                GLib.Variant("(osa{sv})", (PROFILE_PATH, CONTROL_UUID, options)),
                None, Gio.DBusCallFlags.NONE, 5000, None,
            )
        except GLib.Error as exc:
            self._bus.unregister_object(self._registration)
            self._registration = None
            raise BluezError(_("Could not register the RFCOMM profile: {error}").format(error=_error_text(exc))) from exc
        self._registered = True

    def unregister(self) -> None:
        if self._registered:
            try:
                self._bus.call_sync(
                    BLUEZ, "/org/bluez", PROFILE_MANAGER_IFACE, "UnregisterProfile",
                    GLib.Variant("(o)", (PROFILE_PATH,)), None, Gio.DBusCallFlags.NONE, 2000, None,
                )
            except GLib.Error:
                pass
            self._registered = False
        if self._registration is not None:
            self._bus.unregister_object(self._registration)
            self._registration = None

    def _on_method_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "NewConnection":
            device_path, fd_index, _props = params.unpack()
            fd_list = invocation.get_message().get_unix_fd_list()
            try:
                fd = fd_list.get(fd_index)
            except GLib.Error as exc:
                invocation.return_dbus_error("org.bluez.Error.Rejected", exc.message)
                return
            handler = self._handlers.get(device_path)
            if handler is None:
                os.close(fd)  # conexão de um aparelho que o app não pediu
                invocation.return_dbus_error("org.bluez.Error.Rejected", "unknown device")
                return
            invocation.return_value(None)
            handler[0](device_path, fd)
        elif method == "RequestDisconnection":
            (device_path,) = params.unpack()
            invocation.return_value(None)
            handler = self._handlers.get(device_path)
            if handler is not None:
                handler[1](device_path)
        else:  # Release
            self._registered = False
            invocation.return_value(None)


def connect_device(bus: Gio.DBusConnection, device_path: str, on_done: Callable[[str | None], None]) -> None:
    """Device1.Connect: conecta os perfis de áudio (A2DP/HFP) do aparelho."""

    def finished(source, result):
        try:
            source.call_finish(result)
        except GLib.Error as exc:
            on_done(_error_text(exc))
            return
        on_done(None)

    bus.call(BLUEZ, device_path, DEVICE_IFACE, "Connect", None, None, Gio.DBusCallFlags.NONE,
             _CONNECT_TIMEOUT_MS, None, finished)


def connect_profile(
    bus: Gio.DBusConnection,
    device_path: str,
    on_done: Callable[[str | None], None],
) -> None:
    """Pede ao BlueZ para abrir o canal de controle. `on_done(None)` em caso de sucesso.

    O fd chega antes, por `RfcommProfile.NewConnection`.
    """

    def finished(source, result):
        try:
            source.call_finish(result)
        except GLib.Error as exc:
            on_done(_error_text(exc))
            return
        on_done(None)

    bus.call(
        BLUEZ, device_path, DEVICE_IFACE, "ConnectProfile",
        GLib.Variant("(s)", (CONTROL_UUID,)), None, Gio.DBusCallFlags.NONE,
        _CONNECT_TIMEOUT_MS, None, finished,
    )


def disconnect_profile(bus: Gio.DBusConnection, device_path: str, wait: bool = False) -> None:
    """Device1.DisconnectProfile do UUID de controle. Com `wait`, espera a resposta (ao fechar o
    app o main loop já parou e uma chamada assíncrona se perderia)."""
    args = (BLUEZ, device_path, DEVICE_IFACE, "DisconnectProfile", GLib.Variant("(s)", (CONTROL_UUID,)),
            None, Gio.DBusCallFlags.NONE, 5000, None)
    if wait:
        try:
            bus.call_sync(*args)
        except GLib.Error:
            pass
        return
    bus.call(*args, lambda source, result: _ignore_errors(source, result))


def _ignore_errors(source, result) -> None:
    try:
        source.call_finish(result)
    except GLib.Error:
        pass


def watch_device(
    bus: Gio.DBusConnection,
    device_path: str,
    on_connected_changed: Callable[[bool], None],
) -> int:
    """Assina mudanças de `Device1.Connected`. Devolve o id para `bus.signal_unsubscribe`."""

    def on_signal(_conn, _sender, _path, _iface, _signal, params):
        iface, changed, _invalidated = params.unpack()
        if iface == DEVICE_IFACE and "Connected" in changed:
            on_connected_changed(bool(changed["Connected"]))

    return bus.signal_subscribe(
        BLUEZ, PROPERTIES_IFACE, "PropertiesChanged", device_path, None,
        Gio.DBusSignalFlags.NONE, on_signal,
    )


def device_connected(bus: Gio.DBusConnection, device_path: str) -> bool:
    try:
        reply = bus.call_sync(
            BLUEZ, device_path, PROPERTIES_IFACE, "Get",
            GLib.Variant("(ss)", (DEVICE_IFACE, "Connected")),
            GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
    except GLib.Error:
        return False
    return bool(reply.unpack()[0])
