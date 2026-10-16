"""Valores e construtores de comandos (docs/PROTOCOLO.md §3, §4 e §12).

Não há aqui nenhuma escrita de manutenção (firmware, reset, diagnóstico). Cada construtor
devolve um `Frame`; quem envia é o transporte.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import IntEnum

from .frame import Frame
from .ids import MsgId


class Preset(IntEnum):
    NORMAL = 0
    BASS_BOOST = 1
    SOFT = 2
    DYNAMIC = 3
    CLEAR = 4
    TREBLE_BOOST = 5


PRESET_KEYS: dict[str, Preset] = {
    "normal": Preset.NORMAL,
    "bass": Preset.BASS_BOOST,
    "soft": Preset.SOFT,
    "dynamic": Preset.DYNAMIC,
    "clear": Preset.CLEAR,
    "treble": Preset.TREBLE_BOOST,
}


class NoiseControl(IntEnum):
    OFF = 0
    ANC = 1
    AMBIENT = 2


NOISE_KEYS: dict[str, NoiseControl] = {
    "off": NoiseControl.OFF,
    "anc": NoiseControl.ANC,
    "ambient": NoiseControl.AMBIENT,
}


class TouchHoldOption(IntEnum):
    """Ação do "tocar e segurar" (TouchAndHoldActivity.W)."""

    VOICE_ASSISTANT = 1  # assistente do celular
    NOISE_CONTROLS = 2
    VOLUME = 3  # esquerdo abaixa, direito aumenta
    INTERPRETER = 4  # app do celular
    MINDFULNESS = 5  # app do celular
    SPOTIFY = 6  # app do celular


# Opções que fazem sentido sem um celular Samsung.
LINUX_TOUCH_HOLD_OPTIONS = (TouchHoldOption.NOISE_CONTROLS, TouchHoldOption.VOLUME)

BALANCE_MIN = 0
BALANCE_MAX = 32
BALANCE_CENTER = 16  # padrão de fábrica observado no SM-R410

# Volume do som ambiente por lado: o APK limita a 0..2 (`EnhancementAmbientVolumeActivity.R`)
# e usa 4 para o "volume extra-alto".
AMBIENT_VOLUME_MAX = 2
AMBIENT_VOLUME_EXTRA_HIGH = 4


class FitResult(IntEnum):
    GOOD = 1  # FitTestActivity.f14172S
    TOO_NOISY = 2  # FitTestActivity.f14173T
    # Qualquer outro valor: encaixe ruim.


@dataclass(frozen=True)
class TouchSettings:
    """Gestos do touchpad. True = gesto ativo (confirmado no SM-R410)."""

    touch_controls: bool
    tap: bool
    double_tap: bool
    triple_tap: bool
    touch_and_hold: bool
    calls_double_tap: bool
    calls_touch_and_hold: bool

    # Bits do offset 10 do 0x61 (`g8.l`).
    _STATUS_BITS = {
        "touch_and_hold": 0,
        "triple_tap": 1,
        "double_tap": 2,
        "tap": 3,
        "calls_double_tap": 4,
        "calls_touch_and_hold": 5,
        "touch_controls": 7,
    }

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_status_byte(cls, value: int) -> "TouchSettings":
        return cls(**{name: bool(value >> bit & 1) for name, bit in cls._STATUS_BITS.items()})

    @classmethod
    def from_payload(cls, payload: bytes) -> "TouchSettings":
        names = cls.names()
        if len(payload) < len(names):
            raise ValueError("payload de toque curto demais")
        return cls(*(payload[i] == 1 for i in range(len(names))))

    def to_payload(self) -> bytes:
        # Ordem do construtor de 0x90 (`g8.r`).
        return bytes(int(getattr(self, name)) for name in self.names())

    def with_(self, **changes: bool) -> "TouchSettings":
        return replace(self, **changes)


@dataclass(frozen=True)
class NoiseCycle:
    """Modos alternados pelo "tocar e segurar" quando a ação é controle de ruído."""

    anc: bool
    ambient: bool
    off: bool

    def to_bytes(self) -> bytes:
        return bytes([int(self.anc), int(self.ambient), int(self.off)])

    def valid(self) -> bool:
        # O app original exige pelo menos dois modos no ciclo.
        return sum((self.anc, self.ambient, self.off)) >= 2


@dataclass(frozen=True)
class AmbientCustomization:
    """Payload de 0x82 (`g8.g`): som ambiente personalizado."""

    enabled: bool
    volume_left: int
    volume_right: int
    tone: int
    conversation_boost: bool
    noise_reduction_level: int

    def to_payload(self) -> bytes:
        return bytes(
            [
                int(self.enabled),
                self.volume_left & 0xFF,
                self.volume_right & 0xFF,
                self.tone & 0xFF,
                int(self.conversation_boost),
                self.noise_reduction_level & 0xFF,
            ]
        )


def _bool(msg_id: MsgId, value: bool) -> Frame:
    return Frame(msg_id, bytes([int(bool(value))]))


def set_preset(preset: int) -> Frame:
    return Frame(MsgId.EQUALIZER, bytes([Preset(preset)]))


def set_noise_control(mode: int) -> Frame:
    return Frame(MsgId.NOISE_CONTROLS, bytes([NoiseControl(mode)]))


def set_balance(value: int) -> Frame:
    if not BALANCE_MIN <= value <= BALANCE_MAX:
        raise ValueError(f"balanço fora de {BALANCE_MIN}..{BALANCE_MAX}: {value}")
    return Frame(MsgId.SOUND_BALANCE, bytes([value]))


def set_touch(settings: TouchSettings) -> Frame:
    return Frame(MsgId.LOCK_TOUCHPAD, settings.to_payload())


def set_touch_hold_option(left: int, right: int) -> Frame:
    return Frame(
        MsgId.TOUCH_AND_HOLD_OPTION, bytes([TouchHoldOption(left), TouchHoldOption(right)])
    )


def set_noise_cycle(first: NoiseCycle, second: NoiseCycle) -> Frame:
    """0x79. [INFERIDO] O primeiro trio é o lado esquerdo (o segundo é `…_RIGHT` no APK)."""
    if not (first.valid() and second.valid()):
        raise ValueError("o ciclo precisa de pelo menos dois modos")
    return Frame(MsgId.NOISE_CYCLE, first.to_bytes() + second.to_bytes())


def set_anc_with_one_earbud(enabled: bool) -> Frame:
    return _bool(MsgId.ANC_WITH_ONE_EARBUD, enabled)


def set_ambient_during_calls(enabled: bool) -> Frame:
    return _bool(MsgId.AMBIENT_DURING_CALLS, enabled)


def set_in_ear_detection(enabled: bool) -> Frame:
    # `C0089c` case 3: envia `!ligado`.
    return _bool(MsgId.IN_EAR_DETECTION, not enabled)


def set_game_mode(enabled: bool) -> Frame:
    return _bool(MsgId.GAME_MODE, enabled)


def set_extra_high_ambient(enabled: bool) -> Frame:
    return _bool(MsgId.EXTRA_HIGH_AMBIENT, enabled)


def set_ambient_customization(value: AmbientCustomization) -> Frame:
    return Frame(MsgId.CUSTOMIZE_AMBIENT, value.to_payload())


def find_start(ring_on_wearing: bool) -> Frame:
    msg = MsgId.FIND_MY_EARBUDS_RING_ON_WEARING if ring_on_wearing else MsgId.FIND_MY_EARBUDS_START
    return Frame(msg)


def find_stop() -> Frame:
    return Frame(MsgId.FIND_MY_EARBUDS_STOP)


def mute_earbuds(left: bool, right: bool) -> Frame:
    return Frame(MsgId.MUTE_EARBUD, bytes([int(left), int(right)]))


def fit_test(start: bool) -> Frame:
    return _bool(MsgId.FIT_TEST, start)


def request_serial_numbers() -> Frame:
    return Frame(MsgId.DEBUG_SERIAL_NUMBER)


def host_ack(msg_id: int) -> Frame:
    """Resposta `[0x00]` com a flag de resposta, como o plugin faz em `e8.m`."""
    return Frame(msg_id, b"\x00", response=True)
