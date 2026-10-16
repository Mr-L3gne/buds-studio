"""Estado do fone e parsers das mensagens recebidas (docs/PROTOCOLO.md §5, §6 e §12)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .ids import MsgId
from .messages import AMBIENT_VOLUME_EXTRA_HIGH, AmbientCustomization, NoiseCycle, TouchSettings

CASE_BATTERY_UNAVAILABLE = 101
_IN_EAR = 1


@dataclass(frozen=True)
class DeviceState:
    revision: int | None = None
    battery_left: int | None = None
    battery_right: int | None = None
    battery_case: int | None = None
    charging_left: bool | None = None
    charging_right: bool | None = None
    charging_case: bool | None = None
    wearing_left: bool | None = None
    wearing_right: bool | None = None
    placement_left: int | None = None  # valor bruto; só 1 (no ouvido) é mapeado no APK
    placement_right: int | None = None
    coupled: bool | None = None
    primary_left: bool | None = None
    equalizer: int | None = None
    noise_control: int | None = None
    touch: TouchSettings | None = None
    touch_hold_left: int | None = None
    touch_hold_right: int | None = None
    noise_cycle_first: NoiseCycle | None = None
    noise_cycle_second: NoiseCycle | None = None
    balance: int | None = None
    game_mode: bool | None = None
    anc_with_one_earbud: bool | None = None
    ambient: AmbientCustomization | None = None
    ambient_during_calls: bool | None = None
    in_ear_detection: bool | None = None
    extended_seen: int = field(default=0, compare=False)

    @property
    def ready(self) -> bool:
        return self.extended_seen > 0

    @property
    def extra_high_ambient(self) -> bool | None:
        # [INFERIDO] O APK só lê esse estado com a feature EXTRA_HEARING_ENHANCEMENT_LV5, que o
        # Core não tem. Ligar o modo grava volume 4 nos dois lados (h7.d / EnhancementAmbient-
        # VolumeActivity), então volume 4 indica o modo ativo.
        if self.ambient is None:
            return None
        return AMBIENT_VOLUME_EXTRA_HIGH in (self.ambient.volume_left, self.ambient.volume_right)


@dataclass(frozen=True)
class DeviceInfo:
    hw_left: int | None = None
    hw_right: int | None = None
    firmware_left: str | None = None
    firmware_right: str | None = None
    touch_fw_left: int | None = None
    touch_fw_right: int | None = None
    serial_left: str | None = None
    serial_right: str | None = None
    case_firmware: str | None = None
    case_serial: str | None = None


@dataclass(frozen=True)
class Ack:
    msg_id: int
    data: bytes


@dataclass(frozen=True)
class FitTestResult:
    left: int
    right: int


@dataclass(frozen=True)
class StatusLayout:
    """Features do modelo que mudam o layout do 0x60/0x61 (`h7.d.O(...)` no parser)."""

    in_ear_detection: bool = True
    charging_status: bool = True
    full_extended: bool = True  # False: só os campos básicos (modelos não analisados)


CORE_LAYOUT = StatusLayout()
BASIC_LAYOUT = StatusLayout(in_ear_detection=False, charging_status=False, full_extended=False)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def has(self, n: int = 1) -> bool:
        return self.pos + n <= len(self.data)

    def byte(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value

    def skip(self, n: int = 1) -> None:
        self.pos += n


def _case_battery(value: int) -> int | None:
    # O APK trata 101 como indisponível; o SM-R410 mandou 255 com o estojo longe.
    return None if value >= CASE_BATTERY_UNAVAILABLE else value


def _placement(value: int) -> dict:
    left, right = value >> 4, value & 0x0F
    return {
        "placement_left": left,
        "placement_right": right,
        "wearing_left": left == _IN_EAR,
        "wearing_right": right == _IN_EAR,
    }


def _charging(value: int) -> dict:
    return {
        "charging_left": bool(value & 0x10),
        "charging_right": bool(value & 0x04),
        "charging_case": bool(value & 0x01),
    }


def apply_status(state: DeviceState, payload: bytes, layout: StatusLayout = CORE_LAYOUT) -> DeviceState:
    """0x60 STATUS_UPDATED (`g8.a.a`, case 96)."""
    r = _Reader(payload)
    changes: dict = {}
    if not r.has(3):
        return state
    changes["revision"] = r.byte()
    changes["battery_left"] = r.byte()
    changes["battery_right"] = r.byte()
    if r.has():
        changes["coupled"] = r.byte() == 1
    if r.has():
        r.skip()
    if r.has():
        changes.update(_placement(r.byte()))
    if r.has():
        changes["battery_case"] = _case_battery(r.byte())
    if layout.charging_status and r.has():
        changes.update(_charging(r.byte()))
    return replace(state, **changes)


def apply_extended_status(
    state: DeviceState, payload: bytes, layout: StatusLayout = CORE_LAYOUT
) -> DeviceState:
    """0x61 EXTENDED_STATUS_UPDATED (`g8.l`). Segue a mesma sequência de leituras do APK e
    para no primeiro campo que não couber no payload."""
    r = _Reader(payload)
    c: dict = {"extended_seen": state.extended_seen + 1}
    try:
        c["revision"] = r.byte()
        r.skip()
        c["battery_left"] = r.byte()
        c["battery_right"] = r.byte()
        if not layout.full_extended:
            return replace(state, **c)
        c["coupled"] = r.byte() == 1
        c["primary_left"] = r.byte() == 1
        c.update(_placement(r.byte()))
        c["battery_case"] = _case_battery(r.byte())
        c["game_mode"] = r.byte() == 1
        c["equalizer"] = r.byte()
        c["touch"] = TouchSettings.from_status_byte(r.byte())
        hold = r.byte()
        c["touch_hold_left"], c["touch_hold_right"] = hold >> 4, hold & 0x0F
        c["noise_control"] = r.byte()
        r.skip()  # 13 voiceWakeUp (Bixby)
        r.skip(4)  # 14..17 dois shorts
        r.skip()  # 18
        r.skip()  # 19 seamlessConnection
        r.skip()  # 20
        cycle = r.byte()  # 21
        c["noise_cycle_second"] = NoiseCycle(
            anc=bool(cycle & 0x04), ambient=bool(cycle & 0x02), off=bool(cycle & 0x01)
        )
        c["noise_cycle_first"] = NoiseCycle(
            anc=bool(cycle & 0x40), ambient=bool(cycle & 0x20), off=bool(cycle & 0x10)
        )
        r.skip()  # 22
        r.skip(2)  # 23, 24
        c["balance"] = r.byte()  # 25
        r.skip()  # 26 voiceDetect
        r.skip()  # 27 voiceDetectDuration
        c["anc_with_one_earbud"] = r.byte() == 1  # 28
        ambient_on = r.byte() == 1  # 29
        volumes = r.byte()  # 30
        tone = r.byte()  # 31
        r.skip()  # 32 doubleTapSide
        c["ambient_during_calls"] = r.byte() == 1  # 33
        if layout.in_ear_detection:
            c["in_ear_detection"] = r.byte() == 0  # 34: 0 = ligado
        r.skip()  # spatialAudio
        boost = r.byte() == 1  # conversationBoost
        nr_level = r.byte()  # customizeNoiseReductionLevel
        c["ambient"] = AmbientCustomization(
            enabled=ambient_on,
            volume_left=volumes >> 4,
            volume_right=volumes & 0x0F,
            tone=tone,
            conversation_boost=boost,
            noise_reduction_level=nr_level,
        )
        r.skip()  # neckStretchCalibration
        r.skip()  # bixbyKeyword
        r.skip()  # hearingTestValue
        r.skip()  # (ignorado pelo APK)
        r.skip()  # spatialAudioHeadTracking
        if layout.charging_status:
            c.update(_charging(r.byte()))
    except IndexError:
        pass
    return replace(state, **c)


def parse_ack(payload: bytes) -> Ack | None:
    """0x42: payload[0] = ID confirmado, restante = valor aplicado."""
    if not payload:
        return None
    return Ack(payload[0], bytes(payload[1:]))


def apply_ack(state: DeviceState, ack: Ack) -> DeviceState:
    """Atualiza o estado com o eco do ack, como `g8.T.f` faz para 0x86, 0x78, 0x90, 0x92 e 0x79."""
    d = ack.data
    if not d:
        return state
    if ack.msg_id == MsgId.EQUALIZER:
        return replace(state, equalizer=d[0])
    if ack.msg_id == MsgId.NOISE_CONTROLS:
        return replace(state, noise_control=d[0])
    if ack.msg_id == MsgId.LOCK_TOUCHPAD and len(d) >= len(TouchSettings.names()):
        return replace(state, touch=TouchSettings.from_payload(d))
    if ack.msg_id == MsgId.TOUCH_AND_HOLD_OPTION and len(d) >= 2:
        return replace(state, touch_hold_left=d[0], touch_hold_right=d[1])
    # Acks vistos no SM-R410 sem case próprio em g8.T.f (o eco é o valor enviado).
    if ack.msg_id == MsgId.SOUND_BALANCE:
        return replace(state, balance=d[0])
    if ack.msg_id == MsgId.ANC_WITH_ONE_EARBUD:
        return replace(state, anc_with_one_earbud=d[0] == 1)
    if ack.msg_id == MsgId.AMBIENT_DURING_CALLS:
        return replace(state, ambient_during_calls=d[0] == 1)
    if ack.msg_id == MsgId.IN_EAR_DETECTION:
        return replace(state, in_ear_detection=d[0] == 0)  # payload invertido
    if ack.msg_id == MsgId.GAME_MODE:
        return replace(state, game_mode=d[0] == 1)
    if ack.msg_id == MsgId.NOISE_CYCLE and len(d) >= 6:
        return replace(
            state,
            noise_cycle_first=NoiseCycle(bool(d[0]), bool(d[1]), bool(d[2])),
            noise_cycle_second=NoiseCycle(bool(d[3]), bool(d[4]), bool(d[5])),
        )
    return state


def apply_noise_update(state: DeviceState, payload: bytes) -> DeviceState:
    """0x77: o fone mudou o modo sozinho (toque longo). [noise, wearing]."""
    if not payload:
        return state
    return replace(state, noise_control=payload[0])


def _ascii(data: bytes) -> str | None:
    text = data.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return text or None


def apply_version_info_long(info: DeviceInfo, payload: bytes) -> DeviceInfo:
    """0x68 (`g8.b0`): hwL, hwR, swL[20], swR[20], touchL, touchR."""
    if len(payload) < 42:
        return info
    changes = {
        "hw_left": payload[0],
        "hw_right": payload[1],
        "firmware_left": _ascii(payload[2:22]),
        "firmware_right": _ascii(payload[22:42]),
    }
    if len(payload) >= 44:
        changes.update(touch_fw_left=payload[42], touch_fw_right=payload[43])
    return replace(info, **changes)


def apply_serial_numbers(info: DeviceInfo, payload: bytes) -> DeviceInfo:
    """0x29 (`g8.j`): serial L[11], serial R[11]."""
    if len(payload) < 22:
        return info
    return replace(info, serial_left=_ascii(payload[0:11]), serial_right=_ascii(payload[11:22]))


def apply_cradle_serial(info: DeviceInfo, payload: bytes) -> DeviceInfo:
    """0xCD (`g8.f`): 9 bytes + 11 bytes.

    [INFERIDO] O log do APK chama os 11 bytes de serialNumber e os 9 de swVersion, mas grava o
    primeiro campo em `case_serial_number_pref_key`. Sigo o log: no SM-R410 os 11 bytes têm o
    formato de um número de série Samsung ("R8AL…").
    """
    if len(payload) < 20:
        return info
    return replace(info, case_firmware=_ascii(payload[0:9]), case_serial=_ascii(payload[9:20]))


def parse_fit_result(payload: bytes) -> FitTestResult | None:
    if len(payload) < 2:
        return None
    return FitTestResult(payload[0], payload[1])
