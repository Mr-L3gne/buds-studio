"""Conexão com um fone: conecta, reconecta quando ele volta e entrega os bytes recebidos."""

from __future__ import annotations

import os
from enum import Enum
from typing import Callable, Protocol

from gi.repository import GLib

from ..i18n import _
from . import bluez
from .link import Link, connect_rfcomm

# Esperas entre tentativas, em segundos. Depois da última, aguarda o BlueZ avisar que o fone
# voltou a se conectar.
_RETRY_DELAYS = (2, 5, 10, 30)
_RECONNECT_AFTER_ACL_S = 2
# Erros passageiros do BlueZ (o enlace anterior ainda caindo, outra operação em curso):
# tenta de novo logo, mesmo sem reconexão automática.
_TRANSIENT_ERRORS = ("br-connection-canceled", "br-connection-aborted-by-local", "br-connection-busy",
                     "Operation already in progress", "InProgress")
_TRANSIENT_RETRIES = 2
_TRANSIENT_DELAY_S = 1


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    WAITING = "waiting"  # aguardando o fone ligar ou sair do estojo


class Transport(Protocol):
    """Interface usada pelos services (o teste usa uma implementação falsa)."""

    on_state: Callable[[ConnectionState, str | None], None]
    on_data: Callable[[bytes], None]
    state: ConnectionState
    auto_reconnect: bool

    def devices(self) -> list[bluez.BluezDevice]: ...
    def connect(self, device: bluez.BluezDevice, channel: int | None = None) -> None: ...
    def disconnect(self) -> None: ...
    def send(self, data: bytes) -> None: ...
    def shutdown(self) -> None: ...


class BluezTransport:
    def __init__(self, auto_reconnect: bool = True) -> None:
        self.on_state: Callable[[ConnectionState, str | None], None] = lambda *_: None
        self.on_data: Callable[[bytes], None] = lambda _data: None
        self.auto_reconnect = auto_reconnect
        self.state = ConnectionState.DISCONNECTED
        self._bus = None
        self._profile: bluez.RfcommProfile | None = None
        self._device: bluez.BluezDevice | None = None
        self._channel: int | None = None
        self._link: Link | None = None
        self._signal_id: int | None = None
        self._retry_source: int | None = None
        self._attempt = 0
        self._transient_attempt = 0
        self._wanted = False

    @property
    def device(self) -> bluez.BluezDevice | None:
        return self._device

    @property
    def connected(self) -> bool:
        return self._link is not None and self._link.open

    def devices(self) -> list[bluez.BluezDevice]:
        return bluez.list_devices(self._get_bus())

    def connect(self, device: bluez.BluezDevice, channel: int | None = None) -> None:
        """Conecta ao fone. Com `channel`, abre RFCOMM direto nesse canal (diagnóstico)."""
        if (
            channel is None and self._channel is None and self._wanted and self._device is not None
            and self._device.path == device.path
            and self.state in (ConnectionState.CONNECTING, ConnectionState.CONNECTED)
        ):
            return  # já conectando/conectado a este fone: reiniciar abortaria o ConnectProfile
        self._stop(notify=False)
        bus = self._get_bus()
        self._device = device
        self._channel = channel
        self._wanted = True
        self._attempt = 0
        self._transient_attempt = 0
        if channel is None:
            profile = bluez.RfcommProfile.shared(bus)
            profile.add(device.path, self._on_new_connection, self._on_disconnect_request)
            self._profile = profile
        self._signal_id = bluez.watch_device(bus, device.path, self._on_acl_changed)
        self._connect_now()

    def disconnect(self) -> None:
        self._stop(notify=True)

    def shutdown(self) -> None:
        self._stop(notify=False, wait=True)
        if self._profile is not None and self._device is not None:
            self._profile.remove(self._device.path)
        self._profile = None

    def send(self, data: bytes) -> None:
        if self._link is None:
            raise OSError(_("Not connected to the earbuds"))
        self._link.send(data)

    def _stop(self, notify: bool, wait: bool = False) -> None:
        self._wanted = False
        self._cancel_retry()
        if self._signal_id is not None and self._bus is not None:
            self._bus.signal_unsubscribe(self._signal_id)
            self._signal_id = None
        if self._link is not None:
            self._link.close(notify=False)
            self._link = None
            if self._device is not None and self._channel is None:
                # Primeiro desconecta o perfil; só depois tira o fone do Profile1 compartilhado.
                # Na ordem inversa o BlueZ fica com a conexão anterior pendurada e o próximo
                # ConnectProfile falha com br-connection-aborted-by-local.
                bluez.disconnect_profile(self._bus, self._device.path, wait=wait)
        if self._profile is not None and self._device is not None:
            self._profile.remove(self._device.path)
            self._profile = None
        if notify:
            self._set_state(ConnectionState.DISCONNECTED, None)
        else:
            self.state = ConnectionState.DISCONNECTED

    def _get_bus(self):
        if self._bus is None:
            self._bus = bluez.system_bus()
        return self._bus

    def _connect_now(self) -> bool:
        self._retry_source = None
        if not self._wanted or self._device is None or self.connected:
            return GLib.SOURCE_REMOVE
        self._set_state(ConnectionState.CONNECTING, self._device.name)
        if self._channel is not None:
            connect_rfcomm(self._device.address, self._channel, self._on_fd, self._on_connect_failed)
        else:
            bluez.connect_profile(self._bus, self._device.path, self._on_profile_done)
        return GLib.SOURCE_REMOVE

    def _on_profile_done(self, error: str | None) -> None:
        if error is not None and not self.connected:
            self._on_connect_failed(error)

    def _on_new_connection(self, device_path: str, fd: int) -> None:
        if self._device is None or device_path != self._device.path or not self._wanted:
            os.close(fd)  # conexão que não pedimos
            return
        self._on_fd(fd)

    def _on_fd(self, fd: int) -> None:
        if self._link is not None:
            self._link.close(notify=False)
        self._link = Link(fd, self.on_data, self._on_link_closed)
        self._attempt = 0
        self._transient_attempt = 0
        self._set_state(ConnectionState.CONNECTED, self._device.name if self._device else None)

    def _on_link_closed(self, reason: str | None) -> None:
        self._link = None
        if not self._wanted:
            self._set_state(ConnectionState.DISCONNECTED, reason)
            return
        self._retry_or_wait(reason)

    def _on_connect_failed(self, error: str) -> None:
        if not self._wanted:
            return
        if any(t in error for t in _TRANSIENT_ERRORS) and self._transient_attempt < _TRANSIENT_RETRIES:
            self._transient_attempt += 1
            self._schedule(_TRANSIENT_DELAY_S)
            return
        self._retry_or_wait(error)

    def _retry_or_wait(self, reason: str | None) -> None:
        if not self.auto_reconnect:
            self._wanted = False
            self._set_state(ConnectionState.DISCONNECTED, reason)
            return
        acl_up = self._device is not None and bluez.device_connected(self._bus, self._device.path)
        if acl_up and self._attempt < len(_RETRY_DELAYS):
            delay = _RETRY_DELAYS[self._attempt]
            self._attempt += 1
            self._set_state(ConnectionState.WAITING, reason)
            self._schedule(delay)
        else:
            self._set_state(ConnectionState.WAITING, reason)

    def _on_acl_changed(self, connected: bool) -> None:
        if connected and self._wanted and not self.connected:
            self._attempt = 0
            self._schedule(_RECONNECT_AFTER_ACL_S)

    def _on_disconnect_request(self, device_path: str) -> None:
        if self._device is not None and device_path == self._device.path and self._link is not None:
            self._link.close(_("BlueZ closed the connection"))

    def _schedule(self, seconds: int) -> None:
        self._cancel_retry()
        self._retry_source = GLib.timeout_add_seconds(seconds, self._connect_now)

    def _cancel_retry(self) -> None:
        if self._retry_source is not None:
            GLib.source_remove(self._retry_source)
            self._retry_source = None

    def _set_state(self, state: ConnectionState, detail: str | None) -> None:
        self.state = state
        self.on_state(state, detail)
