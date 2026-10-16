"""Codificação e separação de quadros (docs/PROTOCOLO.md §2).

    FD | HDR lo | HDR hi | MsgID | payload | CRC lo | CRC hi | DD

HDR (16 bits LE): bits 0–9 = MsgID + payload + CRC; bit 12 = resposta [INFERIDO].
O CRC cobre MsgID + payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from .crc import crc16_xmodem

SOM = 0xFD
EOM = 0xDD

LENGTH_MASK = 0x03FF
FLAG_RESPONSE = 0x1000
FLAG_FRAGMENT = 0x2000

# SOM + HDR(2) + EOM; o restante (MsgID, payload, CRC) é contado em LEN.
_OVERHEAD = 4
_MAX_LEN = LENGTH_MASK


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    msg_id: int
    payload: bytes = b""
    response: bool = False
    fragment: bool = False

    def encode(self) -> bytes:
        if not 0 <= self.msg_id <= 0xFF:
            raise FrameError(f"msg_id fora de 0..255: {self.msg_id}")
        length = 1 + len(self.payload) + 2
        if length > _MAX_LEN:
            raise FrameError(f"payload grande demais ({len(self.payload)} bytes)")
        header = length
        if self.response:
            header |= FLAG_RESPONSE
        if self.fragment:
            header |= FLAG_FRAGMENT
        body = bytes([self.msg_id]) + bytes(self.payload)
        crc = crc16_xmodem(body)
        return (
            bytes([SOM, header & 0xFF, header >> 8])
            + body
            + bytes([crc & 0xFF, crc >> 8, EOM])
        )


def decode(raw: bytes) -> Frame:
    """Decodifica exatamente um quadro completo."""
    if len(raw) < _OVERHEAD + 3:
        raise FrameError("quadro curto demais")
    if raw[0] != SOM or raw[-1] != EOM:
        raise FrameError("marcadores SOM/EOM inválidos")
    header = raw[1] | (raw[2] << 8)
    length = header & LENGTH_MASK
    if length + _OVERHEAD != len(raw):
        raise FrameError(f"tamanho declarado {length} não bate com {len(raw)} bytes")
    body = raw[3:-3]
    received_crc = raw[-3] | (raw[-2] << 8)
    if crc16_xmodem(body) != received_crc:
        raise FrameError("CRC inválido")
    return Frame(
        msg_id=body[0],
        payload=bytes(body[1:]),
        response=bool(header & FLAG_RESPONSE),
        fragment=bool(header & FLAG_FRAGMENT),
    )


class FrameReader:
    """Acumula bytes do stream RFCOMM e devolve quadros completos.

    Bytes que não iniciam um quadro válido são descartados um a um até achar o próximo SOM,
    para que lixo ou um quadro corrompido não travem o stream.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.errors: list[str] = []

    def feed(self, data: bytes) -> list[Frame]:
        self._buf.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buf.find(SOM)
            if start < 0:
                self._buf.clear()
                break
            if start:
                del self._buf[:start]
            if len(self._buf) < 3:
                break
            length = (self._buf[1] | (self._buf[2] << 8)) & LENGTH_MASK
            total = length + _OVERHEAD
            if length < 3:
                self.errors.append("tamanho declarado inválido")
                del self._buf[0]
                continue
            if len(self._buf) < total:
                break
            candidate = bytes(self._buf[:total])
            try:
                frames.append(decode(candidate))
            except FrameError as exc:
                self.errors.append(str(exc))
                del self._buf[0]
                continue
            del self._buf[:total]
        return frames
