"""Protocolo dos Galaxy Buds (formato do Buds Core): puro, sem I/O, testável sem hardware."""

from .frame import Frame, FrameError, FrameReader, decode
from .ids import MsgId
from .messages import (
    AmbientCustomization,
    NoiseControl,
    NoiseCycle,
    Preset,
    TouchHoldOption,
    TouchSettings,
)
from .models import Cap, Model, detect_model
from .session import Session, Update
from .status import Ack, DeviceInfo, DeviceState, FitTestResult, StatusLayout

__all__ = [
    "Ack",
    "AmbientCustomization",
    "Cap",
    "DeviceInfo",
    "DeviceState",
    "FitTestResult",
    "Frame",
    "FrameError",
    "FrameReader",
    "Model",
    "MsgId",
    "NoiseControl",
    "NoiseCycle",
    "Preset",
    "Session",
    "StatusLayout",
    "TouchHoldOption",
    "TouchSettings",
    "Update",
    "decode",
    "detect_model",
]
