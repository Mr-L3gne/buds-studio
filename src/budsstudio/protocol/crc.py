"""CRC-16/XMODEM (poly 0x1021, init 0, sem reflexão, sem XOR final).

Ver docs/PROTOCOLO.md §2 "CRC". Implementação bit a bit própria; a tabela não é necessária
para o volume de dados deste protocolo.
"""

_POLY = 0x1021


def crc16_xmodem(data: bytes, crc: int = 0) -> int:
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc
