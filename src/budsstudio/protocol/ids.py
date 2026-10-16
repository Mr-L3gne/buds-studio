"""IDs de mensagem do plugin `pianomgr` (docs/PROTOCOLO.md). Nenhum ID fora do APK."""

from enum import IntEnum


class MsgId(IntEnum):
    # Recebidas
    UNIVERSAL_ACK = 0x42  # g8.T
    STATUS_UPDATED = 0x60  # g8.P
    EXTENDED_STATUS_UPDATED = 0x61  # g8.l
    VERSION_INFO = 0x63  # g8.a0 (formato antigo; o Core manda 0x68)
    VERSION_INFO_LONG = 0x68  # g8.b0
    NOISE_CONTROLS_UPDATE = 0x77  # g8.D: o fone mudou o modo (toque longo)
    FIT_TEST_RESULT = 0x9E  # g8.e
    CRADLE_SERIAL_NUMBER = 0xCD  # g8.f

    # Enviadas
    DEBUG_SERIAL_NUMBER = 0x29  # g8.j (pedido vazio; resposta com os seriais L/R)
    IN_EAR_DETECTION = 0x6E  # payload invertido: 1 = desligado
    ANC_WITH_ONE_EARBUD = 0x6F  # g8.E
    NOISE_CONTROLS = 0x78
    NOISE_CYCLE = 0x79  # g8.M (SET_TOUCH_AND_HOLD_NOISE_CONTROLS)
    CUSTOMIZE_AMBIENT = 0x82  # g8.g
    GAME_MODE = 0x85  # ADJUST_SOUND_SYNC
    EQUALIZER = 0x86
    AMBIENT_DURING_CALLS = 0x8B
    SOUND_BALANCE = 0x8F
    LOCK_TOUCHPAD = 0x90  # g8.r
    TOUCH_AND_HOLD_OPTION = 0x92  # g8.N
    EXTRA_HIGH_AMBIENT = 0x96
    FIT_TEST = 0x9D
    FIND_MY_EARBUDS_START = 0xA0
    FIND_MY_EARBUDS_STOP = 0xA1
    MUTE_EARBUD = 0xA2
    FIND_MY_EARBUDS_RING_ON_WEARING = 0xA6  # usado quando há RING_ON_WEARING (K7.b.b)


# Mensagens do fone que o app responde com `[0x00]` e a flag de resposta (e8.m).
ACKNOWLEDGED_BY_HOST = frozenset(
    {
        MsgId.STATUS_UPDATED,
        MsgId.EXTENDED_STATUS_UPDATED,
        MsgId.VERSION_INFO,
        MsgId.VERSION_INFO_LONG,
    }
)
