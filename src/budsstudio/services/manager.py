"""Vários fones ao mesmo tempo: um `DeviceService` (conexão RFCOMM, sessão e estado) por fone.

`SelectedDevice` expõe à interface o fone escolhido com a mesma API do `DeviceService`; trocar
de fone não desconecta os outros.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import GObject

from ..transport.bluez import BluezDevice, BluezError
from ..transport.connection import BluezTransport, ConnectionState
from ..protocol import detect_model
from .device import DEVICE_SIGNALS, DeviceService


class _NullTransport:
    """Transporte vazio para quando nenhum fone está selecionado."""

    def __init__(self) -> None:
        self.on_state = lambda *_: None
        self.on_data = lambda _d: None
        self.state = ConnectionState.DISCONNECTED
        self.auto_reconnect = False

    def devices(self):
        return []

    def connect(self, device, channel=None):
        pass

    def disconnect(self):
        pass

    def send(self, data):
        raise OSError("no device")

    def shutdown(self):
        pass


class DeviceManager(GObject.Object):
    __gsignals__ = {
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "selected-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # algum fone mudou de estado (bateria, conexão…): address
        "device-updated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(
        self,
        lister: Callable[[], list[BluezDevice]] | None = None,
        transport_factory: Callable[[], object] | None = None,
        auto_reconnect: bool = True,
    ) -> None:
        super().__init__()
        self.auto_reconnect = auto_reconnect
        self._transport_factory = transport_factory or (lambda: BluezTransport(auto_reconnect=self.auto_reconnect))
        self._lister = lister
        self.services: dict[str, DeviceService] = {}  # endereço → serviço (ordem de inclusão)
        self.selected_address: str | None = None
        self._null = DeviceService(_NullTransport())
        self.on_service_created: Callable[[DeviceService], None] = lambda _s: None

    # Consulta

    def paired(self) -> list[BluezDevice]:
        if self._lister is not None:
            return self._lister()
        return BluezTransport().devices()

    @property
    def selected(self) -> DeviceService:
        return self.services.get(self.selected_address or "", self._null)

    def get(self, address: str) -> DeviceService | None:
        return self.services.get(address.upper())

    def find(self, query: str) -> DeviceService | None:
        """Por endereço ou nome (apelido ou nome do fone), sem diferenciar maiúsculas."""
        q = query.strip().casefold()
        for address, service in self.services.items():
            dev = service.device
            names = {address.casefold()}
            if dev is not None:
                names |= {dev.name.casefold(), dev.remote_name.casefold()}
            if q in names:
                return service
        return None

    def connected_services(self) -> list[DeviceService]:
        return [s for s in self.services.values() if s.connected]

    # Alterações

    def add(self, device: BluezDevice, connect: bool = True) -> DeviceService:
        address = device.address.upper()
        service = self.services.get(address)
        if service is None:
            service = DeviceService(self._transport_factory())
            service.device = device
            self.services[address] = service
            for signal in ("connection-changed", "state-changed", "info-changed"):
                service.connect(signal, lambda *_a, a=address: self.emit("device-updated", a))
            self.on_service_created(service)
            self.emit("devices-changed")
        else:
            service.device = device
        service.model = detect_model(device.remote_name or device.name)
        if connect and not service.connected and service.connection == ConnectionState.DISCONNECTED:
            service.connect_device(device)
        if self.selected_address is None:
            self.select(address)
        return service

    def connect_device(self, address: str, channel: int | None = None) -> None:
        service = self.get(address)
        if service is not None and service.device is not None:
            service.connect_device(service.device, channel)

    def forget(self, address: str) -> None:
        """Tira o fone do app (desconecta) sem despareá-lo do sistema."""
        address = address.upper()
        service = self.services.pop(address, None)
        if service is None:
            return
        service.shutdown()
        if self.selected_address == address:
            self.selected_address = next(iter(self.services), None)
            self.emit("selected-changed")
        self.emit("devices-changed")

    def select(self, address: str | None) -> None:
        address = address.upper() if address else None
        if address is not None and address not in self.services:
            return
        if address != self.selected_address:
            self.selected_address = address
            self.emit("selected-changed")

    def shutdown(self) -> None:
        for service in self.services.values():
            service.shutdown()


class SelectedDevice(GObject.Object):
    """Proxy do fone selecionado: mesma API e mesmos sinais do `DeviceService`.

    Ao trocar de fone, reemite connection-changed/state-changed/info-changed/find-changed para a
    interface se atualizar com o estado do novo fone.
    """

    __gsignals__ = dict(DEVICE_SIGNALS)

    _RELAYED = tuple(DEVICE_SIGNALS)

    def __init__(self, manager: DeviceManager) -> None:
        super().__init__()
        self._manager = manager
        self._target: DeviceService | None = None
        self._handlers: list[int] = []
        manager.connect("selected-changed", lambda *_: self._retarget())
        self._retarget()

    @property
    def target(self) -> DeviceService:
        return self._manager.selected

    def _retarget(self) -> None:
        if self._target is not None:
            for handler in self._handlers:
                if self._target.handler_is_connected(handler):
                    self._target.disconnect(handler)
        self._handlers = []
        self._target = self._manager.selected
        for signal in self._RELAYED:
            self._handlers.append(
                self._target.connect(signal, lambda _s, *args, sig=signal: self.emit(sig, *args))
            )
        self.emit("connection-changed", self._target.connection.value, "")
        self.emit("state-changed")
        self.emit("info-changed")
        self.emit("find-changed", self._target.finding)

    def __getattr__(self, name):
        # Só chamado para o que não existe no proxy: repassa ao fone selecionado.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._manager.selected, name)


__all__ = ["BluezError", "DeviceManager", "SelectedDevice"]
