"""Curvas do EQ do computador: presets e o cálculo da folga (headroom) contra distorção.

Sem GLib/PipeWire, para a CLI e os testes poderem importar sem custo.
"""

from __future__ import annotations

import cmath
import math

from .config import SYSTEM_EQ_BANDS_HZ

Q = 1.41
_SAMPLE_RATE = 48000

# Curvas prontas para as 10 bandas (31 Hz … 16 kHz). Os nomes ficam na interface (traduzíveis).
SYSTEM_EQ_PRESETS: dict[str, tuple[float, ...]] = {
    "flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "bass": (6, 5, 4, 2, 0, 0, 0, 0, 0, 0),
    "treble": (0, 0, 0, 0, 0, 1, 2, 4, 5, 6),
    "vocal": (-3, -2, -1, 0, 2, 3, 4, 3, 1, 0),
    "loudness": (5, 4, 2, 0, -1, -1, 0, 2, 4, 5),
    "soft": (2, 2, 1, 0, 0, 0, -1, -2, -3, -3),
}


def preset_gains(name: str) -> list[float] | None:
    values = SYSTEM_EQ_PRESETS.get(name)
    return None if values is None else [float(v) for v in values]


def preset_for(gains: list[float]) -> str | None:
    """Nome do preset que tem exatamente estes ganhos (ou None se a curva é personalizada)."""
    for name, values in SYSTEM_EQ_PRESETS.items():
        if all(abs(float(a) - float(b)) < 0.05 for a, b in zip(gains, values)) and len(gains) == len(values):
            return name
    return None


def _peaking_response(freq: float, gain_db: float, at: float) -> complex:
    """Resposta (RBJ, bq_peaking) de uma banda na frequência `at`, a 48 kHz."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * freq / _SAMPLE_RATE
    alpha = math.sin(w0) / (2 * Q)
    b = (1 + alpha * a, -2 * math.cos(w0), 1 - alpha * a)
    d = (1 + alpha / a, -2 * math.cos(w0), 1 - alpha / a)
    z = cmath.exp(-1j * 2 * math.pi * at / _SAMPLE_RATE)
    return (b[0] + b[1] * z + b[2] * z * z) / (d[0] + d[1] * z + d[2] * z * z)


def headroom_db(gains: list[float]) -> float:
    """Maior reforço, em dB, que a curva soma em qualquer frequência (0 se só corta).

    As bandas vizinhas se sobrepõem, então o pico real passa do maior ganho individual. Reduzir o
    volume geral por este valor impede que as bandas reforçadas distorçam (clipping).
    """
    if not any(g > 0 for g in gains):
        return 0.0
    peak = 0.0
    for i in range(193):  # 20 Hz … 20 kHz em passos de 1/24 de oitava
        at = 20 * 2 ** (i / 24)
        total = 1 + 0j
        for freq, gain in zip(SYSTEM_EQ_BANDS_HZ, gains):
            if gain:
                total *= _peaking_response(freq, float(gain), at)
        peak = max(peak, 20 * math.log10(abs(total)))
    return round(peak, 2)


def preamp_mult(gains: list[float], enabled: bool = True) -> float:
    """Multiplicador linear do nó `preamp` (1.0 sem compensação)."""
    return round(10 ** (-headroom_db(gains) / 20), 4) if enabled else 1.0
