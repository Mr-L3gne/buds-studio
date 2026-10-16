"""Modelos conhecidos e o que cada um suporta.

Os nomes e plugins vêm do Galaxy Wearable (`b7.l.a`). As capacidades do Galaxy Buds Core vêm
do conjunto fixo de features do `pianomgr` (`h7.e.a`) e das telas que o plugin mostra.
Os outros modelos não tiveram o plugin analisado: só o básico fica ativo, como experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Cap(str, Enum):
    BATTERY = "battery"
    CHARGING = "charging"  # feature CHARGING_STATUS
    WEARING = "wearing"
    EQ_PRESETS = "eq_presets"
    NOISE_CONTROL = "noise_control"  # AMBIENT_SOUND + ANC
    ANC_WITH_ONE_EARBUD = "anc_with_one_earbud"
    NOISE_CYCLE = "noise_cycle"
    AMBIENT_DURING_CALLS = "ambient_during_calls"
    AMBIENT_CUSTOMIZATION = "ambient_customization"  # CUSTOMIZED_AMBIENT_SOUND
    EXTRA_HIGH_AMBIENT = "extra_high_ambient"  # Labs
    IN_EAR_DETECTION = "in_ear_detection"
    GAME_MODE = "game_mode"  # Labs
    BALANCE = "balance"
    TOUCH_LOCK = "touch_lock"
    TOUCH_FOR_CALLS = "touch_for_calls"  # TOUCH_CONTROL_FOR_CALLS
    TOUCH_HOLD_OPTION = "touch_hold_option"
    FIND_MY_EARBUDS = "find_my_earbuds"  # OFFLINE_FINDING / Find
    RING_ON_WEARING = "ring_on_wearing"
    FIT_TEST = "fit_test"  # EARBUD_FIT_TEST
    DEVICE_INFO = "device_info"


@dataclass(frozen=True)
class Model:
    key: str
    name: str  # nome Bluetooth anunciado
    plugin: str  # pacote do plugin no Galaxy Wearable
    capabilities: frozenset[Cap]
    validated: bool  # testado em hardware real
    # Pelo menos o formato de quadro do Core (SOM 0xFD) é usado; o Buds original (2019)
    # usa outro formato e não é suportado.
    supported: bool = True

    def has(self, cap: Cap) -> bool:
        return cap in self.capabilities


BUDS_CORE_CAPS = frozenset(Cap)

# [INFERIDO] Para modelos sem plugin analisado, só o que é comum ao formato de quadro e aos
# IDs mais antigos (EQ 0x86, ruído 0x78, bateria nos offsets 2/3 do 0x61). Experimental.
EXPERIMENTAL_CAPS = frozenset({Cap.BATTERY, Cap.EQ_PRESETS, Cap.NOISE_CONTROL})
EXPERIMENTAL_NO_ANC_CAPS = frozenset({Cap.BATTERY, Cap.EQ_PRESETS})

MODELS: tuple[Model, ...] = (
    Model("core", "Galaxy Buds Core", "com.samsung.accessory.pianomgr", BUDS_CORE_CAPS, True),
    Model("buds3_pro", "Galaxy Buds3 Pro", "com.samsung.accessory.paranmgr", EXPERIMENTAL_CAPS, False),
    Model("buds3_fe", "Galaxy Buds3 FE", "com.samsung.accessory.gemstonemgr", EXPERIMENTAL_CAPS, False),
    Model("buds3", "Galaxy Buds3", "com.samsung.accessory.jellymgr", EXPERIMENTAL_CAPS, False),
    Model("buds_fe", "Galaxy Buds FE", "com.samsung.accessory.pearlmgr", EXPERIMENTAL_CAPS, False),
    Model("buds2_pro", "Galaxy Buds2 Pro", "com.samsung.accessory.zenithmgr", EXPERIMENTAL_CAPS, False),
    Model("buds2", "Galaxy Buds2", "com.samsung.accessory.berrymgr", EXPERIMENTAL_CAPS, False),
    Model("buds_pro", "Galaxy Buds Pro", "com.samsung.accessory.atticmgr", EXPERIMENTAL_CAPS, False),
    Model("buds_live", "Galaxy Buds Live", "com.samsung.accessory.neobeanmgr", EXPERIMENTAL_CAPS, False),
    Model("buds_plus", "Galaxy Buds+", "com.samsung.accessory.popcornmgr", EXPERIMENTAL_NO_ANC_CAPS, False),
    Model("buds", "Galaxy Buds", "com.samsung.accessory.fridaymgr", frozenset(), False, supported=False),
)

UNKNOWN_MODEL = Model("unknown", "", "", EXPERIMENTAL_NO_ANC_CAPS, False)


def detect_model(bluetooth_name: str) -> Model:
    """Escolhe o modelo pelo nome Bluetooth. Os nomes mais longos são testados primeiro, para
    que "Galaxy Buds3 Pro" não caia em "Galaxy Buds3"."""
    name = (bluetooth_name or "").strip()
    for model in sorted(MODELS, key=lambda m: len(m.name), reverse=True):
        if name == model.name or name.startswith(model.name + " ") or name.startswith(model.name + "("):
            return model
    return UNKNOWN_MODEL
