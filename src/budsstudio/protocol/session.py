"""Máquina de estado da conversa com o fone, sem I/O.

O transporte entrega os bytes recebidos em `feed()` e envia o que vier em `Update.replies`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import messages
from .frame import Frame, FrameReader
from .ids import ACKNOWLEDGED_BY_HOST, MsgId
from .status import (
    CORE_LAYOUT,
    Ack,
    DeviceInfo,
    DeviceState,
    FitTestResult,
    StatusLayout,
    apply_ack,
    apply_cradle_serial,
    apply_extended_status,
    apply_noise_update,
    apply_serial_numbers,
    apply_status,
    apply_version_info_long,
    parse_ack,
    parse_fit_result,
)


@dataclass
class Update:
    replies: list[bytes] = field(default_factory=list)
    acks: list[Ack] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fit_results: list[FitTestResult] = field(default_factory=list)
    changed: bool = False
    info_changed: bool = False


class Session:
    def __init__(self, layout: StatusLayout = CORE_LAYOUT) -> None:
        self._reader = FrameReader()
        self.layout = layout
        self.state = DeviceState()
        self.info = DeviceInfo()

    def feed(self, data: bytes) -> Update:
        update = Update()
        update.frames = self._reader.feed(data)
        update.errors, self._reader.errors = self._reader.errors, []
        state_before, info_before = self.state, self.info
        for frame in update.frames:
            self._handle(frame, update)
        update.changed = self.state != state_before
        update.info_changed = self.info != info_before
        return update

    def _handle(self, frame: Frame, update: Update) -> None:
        # O fone marca o ack 0x42 com a flag de resposta (visto no SM-R410); a flag só serve
        # para não responder a uma resposta.
        msg, payload = frame.msg_id, frame.payload
        if msg in ACKNOWLEDGED_BY_HOST and not frame.response:
            update.replies.append(messages.host_ack(msg).encode())

        if msg == MsgId.STATUS_UPDATED:
            self.state = apply_status(self.state, payload, self.layout)
        elif msg == MsgId.EXTENDED_STATUS_UPDATED and not frame.response:
            self.state = apply_extended_status(self.state, payload, self.layout)
        elif msg == MsgId.UNIVERSAL_ACK:
            ack = parse_ack(payload)
            if ack is not None:
                update.acks.append(ack)
                self.state = apply_ack(self.state, ack)
        elif msg == MsgId.NOISE_CONTROLS_UPDATE:
            self.state = apply_noise_update(self.state, payload)
        elif msg == MsgId.VERSION_INFO_LONG:
            self.info = apply_version_info_long(self.info, payload)
        elif msg == MsgId.DEBUG_SERIAL_NUMBER:
            self.info = apply_serial_numbers(self.info, payload)
        elif msg == MsgId.CRADLE_SERIAL_NUMBER:
            self.info = apply_cradle_serial(self.info, payload)
        elif msg == MsgId.FIT_TEST_RESULT:
            result = parse_fit_result(payload)
            if result is not None:
                update.fit_results.append(result)
