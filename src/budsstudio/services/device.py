"""Estado do fone e comandos de alto nível, sobre o protocolo e o transporte.

Usado igualmente pela interface e pela CLI. Os comandos conferem a capacidade do modelo antes
de enviar; nenhuma escrita de manutenção (firmware, reset) existe aqui.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, replace

from gi.repository import GLib, GObject

from ..i18n import _
from ..protocol import (
    AmbientCustomization,
    Cap,
    DeviceInfo,
    DeviceState,
    Frame,
    Model,
    MsgId,
    NoiseCycle,
    Session,
    TouchSettings,
    Update,
    decode,
    detect_model,
)
from ..protocol import messages as m
from ..protocol.messages import AMBIENT_VOLUME_EXTRA_HIGH, AMBIENT_VOLUME_MAX
from ..protocol.models import UNKNOWN_MODEL
from ..protocol.status import BASIC_LAYOUT, CORE_LAYOUT
from ..transport.bluez import BluezDevice, BluezError
from ..transport.connection import BluezTransport, ConnectionState, Transport

# O plugin para o "Encontrar fones" sozinho depois de 3 minutos (K7.b.b).
FIND_TIMEOUT_S = 180
_PACKET_LOG_SIZE = 1000


class CommandError(Exception):
    pass


@dataclass(frozen=True)
class Packet:
    timestamp: float
    outgoing: bool
    data: bytes
    frame: Frame | None


DEVICE_SIGNALS = {
    # estado da conexão (ConnectionState.value), detalhe
    "connection-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    "info-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    # primeiro 0x61 depois de conectar
    "ready": (GObject.SignalFlags.RUN_FIRST, None, ()),
    "ack": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    "fit-result": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
    "find-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    "packet": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
}


class DeviceService(GObject.Object):
    __gsignals__ = dict(DEVICE_SIGNALS)

    def __init__(self, transport: Transport | None = None, auto_reconnect: bool = True) -> None:
        super().__init__()
        self.transport = transport or BluezTransport(auto_reconnect=auto_reconnect)
        self.transport.on_state = self._on_transport_state
        self.transport.on_data = self._on_data
        self.device: BluezDevice | None = None
        self.model: Model = UNKNOWN_MODEL
        self.session = Session()
        self.packets: deque[Packet] = deque(maxlen=_PACKET_LOG_SIZE)
        self.finding = False
        self.mute_left = False
        self.mute_right = False
        self._find_timeout: int | None = None
        self._fit_running = False
        self._serial_requested = False
        self._saved_ambient: AmbientCustomization | None = None

    # Estado

    @property
    def state(self) -> DeviceState:
        return self.session.state

    @property
    def info(self) -> DeviceInfo:
        return self.session.info

    @property
    def connection(self) -> ConnectionState:
        return self.transport.state

    @property
    def connected(self) -> bool:
        return self.transport.state == ConnectionState.CONNECTED

    def has(self, cap: Cap) -> bool:
        return self.model.has(cap)

    # Conexão

    def devices(self) -> list[BluezDevice]:
        return self.transport.devices()

    def connect_device(self, device: BluezDevice, channel: int | None = None) -> None:
        self.device = device
        self.model = detect_model(device.remote_name or device.name)
        self._reset_session()
        self.transport.connect(device, channel)

    def disconnect_device(self) -> None:
        self._stop_find_timer()
        self.finding = False
        self.transport.disconnect()

    def shutdown(self) -> None:
        if self.finding and self.connected:
            try:
                self._send(m.find_stop())
            except CommandError:
                pass
        self._stop_find_timer()
        self.transport.shutdown()

    def _reset_session(self) -> None:
        layout = CORE_LAYOUT if self.model.key == "core" else BASIC_LAYOUT
        self.session = Session(layout)
        self._serial_requested = False
        self._fit_running = False

    def _on_transport_state(self, state: ConnectionState, detail: str | None) -> None:
        if state == ConnectionState.CONNECTED:
            self._reset_session()
        elif self.finding:
            self.finding = False
            self._stop_find_timer()
            self.emit("find-changed", False)
        self.emit("connection-changed", state.value, detail or "")
        self.emit("state-changed")

    def _on_data(self, data: bytes) -> None:
        was_ready = self.session.state.ready
        update: Update = self.session.feed(data)
        now = time.time()
        for frame in update.frames:
            self._log(Packet(now, False, frame.encode(), frame))
        for reply in update.replies:
            try:
                self._write(reply)
            except OSError:
                pass
        for ack in update.acks:
            self.emit("ack", ack.msg_id)
        for result in update.fit_results:
            self._fit_running = False
            try:
                self._send(m.fit_test(False))
            except CommandError:
                pass
            self.emit("fit-result", result.left, result.right)
        if update.changed:
            self.emit("state-changed")
        if update.info_changed:
            self.emit("info-changed")
        if self.session.state.ready and not was_ready:
            self.emit("ready")
            self._request_serials()

    def _request_serials(self) -> None:
        # O plugin pede os seriais (0x29) quando o estado "coupled" muda (e8.m, 0x60).
        if self._serial_requested or not self.has(Cap.DEVICE_INFO):
            return
        self._serial_requested = True
        try:
            self._send(m.request_serial_numbers())
        except CommandError:
            pass

    # Envio

    def _log(self, packet: Packet) -> None:
        self.packets.append(packet)
        self.emit("packet", packet)

    def _write(self, data: bytes) -> None:
        self.transport.send(data)
        try:
            frame = decode(data)
        except ValueError:
            frame = None
        self._log(Packet(time.time(), True, data, frame))

    def _send(self, frame: Frame) -> None:
        if not self.connected:
            raise CommandError(_("Not connected to the earbuds"))
        try:
            self._write(frame.encode())
        except OSError as exc:
            raise CommandError(str(exc)) from exc

    def _require(self, cap: Cap) -> None:
        if not self.has(cap):
            raise CommandError(_("This model does not support this feature"))

    # Comandos

    def set_preset(self, preset: int) -> None:
        self._require(Cap.EQ_PRESETS)
        self._send(m.set_preset(preset))

    def set_noise_control(self, mode: int) -> None:
        self._require(Cap.NOISE_CONTROL)
        self._send(m.set_noise_control(mode))

    def set_balance(self, value: int) -> None:
        self._require(Cap.BALANCE)
        self._send(m.set_balance(value))
        # Sem ack no APK: o valor só volta no próximo 0x61.
        self._patch_state(balance=value)

    def set_touch(self, settings: TouchSettings) -> None:
        self._require(Cap.TOUCH_LOCK)
        self._send(m.set_touch(settings))

    def set_touch_field(self, name: str, value: bool) -> None:
        current = self.state.touch
        if current is None:
            raise CommandError(_("Touch settings not received yet"))
        self.set_touch(current.with_(**{name: value}))

    def set_touch_hold_options(self, left: int, right: int) -> None:
        self._require(Cap.TOUCH_HOLD_OPTION)
        self._send(m.set_touch_hold_option(left, right))

    def set_noise_cycle(self, first: NoiseCycle, second: NoiseCycle) -> None:
        self._require(Cap.NOISE_CYCLE)
        self._send(m.set_noise_cycle(first, second))

    def set_anc_with_one_earbud(self, enabled: bool) -> None:
        self._require(Cap.ANC_WITH_ONE_EARBUD)
        self._send(m.set_anc_with_one_earbud(enabled))
        self._patch_state(anc_with_one_earbud=enabled)

    def set_ambient_during_calls(self, enabled: bool) -> None:
        self._require(Cap.AMBIENT_DURING_CALLS)
        self._send(m.set_ambient_during_calls(enabled))
        self._patch_state(ambient_during_calls=enabled)

    def set_in_ear_detection(self, enabled: bool) -> None:
        self._require(Cap.IN_EAR_DETECTION)
        self._send(m.set_in_ear_detection(enabled))
        self._patch_state(in_ear_detection=enabled)

    def set_game_mode(self, enabled: bool) -> None:
        self._require(Cap.GAME_MODE)
        self._send(m.set_game_mode(enabled))
        self._patch_state(game_mode=enabled)

    def set_ambient_volume(self, left: int, right: int) -> None:
        """Volume do som ambiente por lado (0..2), mantendo os demais campos do 0x82."""
        self._require(Cap.AMBIENT_CUSTOMIZATION)
        if not (0 <= left <= AMBIENT_VOLUME_MAX and 0 <= right <= AMBIENT_VOLUME_MAX):
            raise CommandError(_("Ambient volume must be between 0 and {max}").format(max=AMBIENT_VOLUME_MAX))
        current = self.state.ambient
        if current is None:
            raise CommandError(_("Ambient settings not received yet"))
        value = AmbientCustomization(
            enabled=True,
            volume_left=left,
            volume_right=right,
            tone=current.tone,
            conversation_boost=current.conversation_boost,
            noise_reduction_level=current.noise_reduction_level,
        )
        self._send(m.set_ambient_customization(value))
        self._patch_state(ambient=value)

    def set_extra_high_ambient(self, enabled: bool) -> None:
        """Volume extra-alto do som ambiente (Labs). Repete o que `h7.d` faz: envia 0x96 e
        depois 0x82 com volume 4 (ligado) ou com os volumes anteriores (desligado)."""
        self._require(Cap.EXTRA_HIGH_AMBIENT)
        current = self.state.ambient
        if current is None:
            raise CommandError(_("Ambient settings not received yet"))
        if enabled:
            self._saved_ambient = current
            left = right = AMBIENT_VOLUME_EXTRA_HIGH
            ambient_on = True
        else:
            saved = self._saved_ambient
            left = saved.volume_left if saved and saved.volume_left <= AMBIENT_VOLUME_MAX else 1
            right = saved.volume_right if saved and saved.volume_right <= AMBIENT_VOLUME_MAX else 1
            ambient_on = saved.enabled if saved else current.enabled
        value = AmbientCustomization(
            ambient_on, left, right, current.tone, current.conversation_boost,
            current.noise_reduction_level,
        )
        self._send(m.set_extra_high_ambient(enabled))
        self._send(m.set_ambient_customization(value))
        self._patch_state(ambient=value)

    def find_start(self) -> None:
        self._require(Cap.FIND_MY_EARBUDS)
        self._send(m.find_start(self.has(Cap.RING_ON_WEARING)))
        self.finding = True
        self.mute_left = self.mute_right = False
        self._stop_find_timer()
        self._find_timeout = GLib.timeout_add_seconds(FIND_TIMEOUT_S, self._on_find_timeout)
        self.emit("find-changed", True)

    def find_stop(self) -> None:
        self._require(Cap.FIND_MY_EARBUDS)
        self._send(m.find_stop())
        self.finding = False
        self._stop_find_timer()
        self.emit("find-changed", False)

    def set_find_mute(self, left: bool, right: bool) -> None:
        self._require(Cap.FIND_MY_EARBUDS)
        self._send(m.mute_earbuds(left, right))
        self.mute_left, self.mute_right = left, right
        self.emit("find-changed", self.finding)

    def _on_find_timeout(self) -> bool:
        self._find_timeout = None
        if self.finding:
            try:
                self.find_stop()
            except CommandError:
                self.finding = False
                self.emit("find-changed", False)
        return GLib.SOURCE_REMOVE

    def _stop_find_timer(self) -> None:
        if self._find_timeout is not None:
            GLib.source_remove(self._find_timeout)
            self._find_timeout = None

    def fit_test_start(self) -> None:
        self._require(Cap.FIT_TEST)
        s = self.state
        if not (s.wearing_left and s.wearing_right):
            raise CommandError(_("Put both earbuds in your ears first"))
        self._send(m.fit_test(True))
        self._fit_running = True

    def fit_test_cancel(self) -> None:
        if self._fit_running:
            self._fit_running = False
            self._send(m.fit_test(False))

    def _patch_state(self, **changes) -> None:
        self.session.state = replace(self.session.state, **changes)
        self.emit("state-changed")


def format_packet(packet) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(packet.timestamp))
    millis = int((packet.timestamp % 1) * 1000)
    arrow = "→" if packet.outgoing else "←"
    name = ""
    if packet.frame is not None:
        try:
            name = MsgId(packet.frame.msg_id).name
        except ValueError:
            name = f"0x{packet.frame.msg_id:02X}"
        if packet.frame.response:
            name += " [resp]"
    return f"{stamp}.{millis:03d} {arrow} {name:<28} {packet.data.hex(' ').upper()}"


__all__ = ["BluezError", "CommandError", "DeviceService", "Packet", "format_packet"]
