"""Quadros de referência.

`*_FRAMES` de envio: gerados pelo encoder do APK (`g8.a.e`) e conferidos no SM-R410.
`REAL_*`: payloads recebidos do SM-R410 em 2026-10-14 (firmware R410XXU0AYI2). No 0xCD o
número de série do estojo foi trocado por um valor fictício do mesmo formato.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def h(text: str) -> bytes:
    return bytes.fromhex(text)


PRESET_FRAMES = {
    0: "FD 04 00 86 00 3E B1 DD",
    1: "FD 04 00 86 01 1F A1 DD",
    2: "FD 04 00 86 02 7C 91 DD",
    3: "FD 04 00 86 03 5D 81 DD",
    4: "FD 04 00 86 04 BA F1 DD",
    5: "FD 04 00 86 05 9B E1 DD",
}
NOISE_FRAMES = {
    0: "FD 04 00 78 00 F0 81 DD",
    1: "FD 04 00 78 01 D1 91 DD",
    2: "FD 04 00 78 02 B2 A1 DD",
}
EXTENDED_STATUS_REPLY = "FD 04 10 61 00 1B 38 DD"
BALANCE_10_FRAME = "FD 04 00 8F 0A EC AA DD"  # enviado ao SM-R410 e relido no 0x61
BALANCE_16_FRAME = "FD 04 00 8F 10 97 19 DD"
TOUCH_TRIPLE_OFF_FRAME = "FD 0A 00 90 01 01 01 00 01 01 01 85 83 DD"
TOUCH_ALL_ON_FRAME = "FD 0A 00 90 01 01 01 01 01 01 01 31 F5 DD"

REAL_EXTENDED_STATUS = h(
    "00 0A 64 64 01 00 11 FF 00 00 BF 22 02 00 42 01 42 01 00 00 04 66 00 00 00 10"
    " 00 01 00 01 11 02 01 00 00 01 01 01 00 00 9D 0E 01 00 01 00 00 00 00 00 00 00"
    " 00 00 00 00"
)
REAL_STATUS_IN_EAR = h("01 64 64 01 00 11 FF 00")
REAL_STATUS_OUT_OF_EAR = h("01 64 64 01 01 22 FF 00")
REAL_VERSION_INFO_LONG = h(
    "10 10 52 34 31 30 58 58 55 30 41 59 49 32 00 00 00 00 00 00 00 00"
    " 52 34 31 30 58 58 55 30 41 59 49 32 00 00 00 00 00 00 00 00 01 01"
)
CRADLE_SERIAL = h("51 52 34 31 30 43 59 43 41") + b"R0AA0000000"
REAL_ACK_EQ_BASS = h("86 01")
REAL_ACK_NOISE_ANC = h("78 01")
REAL_ACK_TOUCH_TRIPLE_OFF = h("90 01 01 01 00 01 01 01")
