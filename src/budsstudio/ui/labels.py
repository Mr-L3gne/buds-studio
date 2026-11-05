"""Rótulos traduzíveis dos valores do protocolo."""

from __future__ import annotations

from ..i18n import _
from ..protocol.messages import NoiseControl, Preset, TouchHoldOption


def preset_labels() -> dict[int, str]:
    return {
        Preset.NORMAL: _("Balanced"),
        Preset.BASS_BOOST: _("Bass boost"),
        Preset.SOFT: _("Smooth"),
        Preset.DYNAMIC: _("Dynamic"),
        Preset.CLEAR: _("Clear"),
        Preset.TREBLE_BOOST: _("Treble boost"),
    }


def noise_labels() -> dict[int, str]:
    return {
        NoiseControl.OFF: _("Off"),
        NoiseControl.ANC: _("Active noise canceling"),
        NoiseControl.AMBIENT: _("Ambient sound"),
    }


def touch_hold_labels() -> dict[int, str]:
    return {
        TouchHoldOption.VOICE_ASSISTANT: _("Voice assistant (phone)"),
        TouchHoldOption.NOISE_CONTROLS: _("Switch noise controls"),
        TouchHoldOption.VOLUME: _("Volume"),
        TouchHoldOption.INTERPRETER: _("Interpreter (phone)"),
        TouchHoldOption.MINDFULNESS: _("Mindfulness (phone)"),
        TouchHoldOption.SPOTIFY: _("Spotify (phone)"),
    }


def connection_labels() -> dict[str, str]:
    return {
        "disconnected": _("Disconnected"),
        "connecting": _("Connecting…"),
        "connected": _("Connected"),
        "waiting": _("Waiting for the earbuds"),
    }


def fit_label(value: int) -> str:
    if value == 1:
        return _("Good fit")
    if value == 2:
        return _("Too much noise to check")
    return _("Poor fit")


def system_eq_preset_labels() -> dict[str, str]:
    """Curvas prontas do EQ do computador (chave em services.system_eq.SYSTEM_EQ_PRESETS)."""
    return {
        "flat": _("Flat"),
        "bass": _("Bass boost"),
        "treble": _("Treble boost"),
        "vocal": _("Vocals"),
        "loudness": _("Loudness"),
        "soft": _("Soft"),
    }
