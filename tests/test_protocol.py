import unittest

from frames import (
    BALANCE_10_FRAME,
    BALANCE_16_FRAME,
    CRADLE_SERIAL,
    EXTENDED_STATUS_REPLY,
    NOISE_FRAMES,
    PRESET_FRAMES,
    REAL_ACK_EQ_BASS,
    REAL_ACK_NOISE_ANC,
    REAL_ACK_TOUCH_TRIPLE_OFF,
    REAL_EXTENDED_STATUS,
    REAL_STATUS_IN_EAR,
    REAL_STATUS_OUT_OF_EAR,
    REAL_VERSION_INFO_LONG,
    TOUCH_ALL_ON_FRAME,
    TOUCH_TRIPLE_OFF_FRAME,
    h,
)

from budsstudio.protocol import (
    AmbientCustomization,
    Cap,
    Frame,
    FrameError,
    FrameReader,
    MsgId,
    NoiseControl,
    NoiseCycle,
    Preset,
    Session,
    TouchSettings,
    decode,
    detect_model,
)
from budsstudio.protocol import messages as m
from budsstudio.protocol.crc import crc16_xmodem
from budsstudio.protocol.status import BASIC_LAYOUT

ALL_ON = TouchSettings(True, True, True, True, True, True, True)


def device_frame(msg_id, payload, response=False):
    return Frame(msg_id, payload, response=response).encode()


class CrcTest(unittest.TestCase):
    def test_xmodem_check_value(self):
        self.assertEqual(crc16_xmodem(b"123456789"), 0x31C3)

    def test_appended_crc_big_endian_gives_zero(self):
        body = h("86 01")
        crc = crc16_xmodem(body)
        self.assertEqual(crc16_xmodem(body + bytes([crc >> 8, crc & 0xFF])), 0)


class EncodeTest(unittest.TestCase):
    def test_presets(self):
        for preset, expected in PRESET_FRAMES.items():
            with self.subTest(preset=preset):
                self.assertEqual(m.set_preset(preset).encode(), h(expected))

    def test_noise(self):
        for mode, expected in NOISE_FRAMES.items():
            with self.subTest(mode=mode):
                self.assertEqual(m.set_noise_control(mode).encode(), h(expected))

    def test_balance_and_touch_sent_to_real_device(self):
        self.assertEqual(m.set_balance(10).encode(), h(BALANCE_10_FRAME))
        self.assertEqual(m.set_balance(16).encode(), h(BALANCE_16_FRAME))
        self.assertEqual(m.set_touch(ALL_ON.with_(triple_tap=False)).encode(), h(TOUCH_TRIPLE_OFF_FRAME))
        self.assertEqual(m.set_touch(ALL_ON).encode(), h(TOUCH_ALL_ON_FRAME))

    def test_host_ack(self):
        self.assertEqual(m.host_ack(MsgId.EXTENDED_STATUS_UPDATED).encode(), h(EXTENDED_STATUS_REPLY))

    def test_simple_setters(self):
        cases = [
            (m.set_anc_with_one_earbud(True), 0x6F, b"\x01"),
            (m.set_ambient_during_calls(False), 0x8B, b"\x00"),
            (m.set_game_mode(True), 0x85, b"\x01"),
            (m.set_extra_high_ambient(True), 0x96, b"\x01"),
            (m.set_in_ear_detection(True), 0x6E, b"\x00"),  # invertido
            (m.set_in_ear_detection(False), 0x6E, b"\x01"),
            (m.fit_test(True), 0x9D, b"\x01"),
            (m.find_start(True), 0xA6, b""),
            (m.find_start(False), 0xA0, b""),
            (m.find_stop(), 0xA1, b""),
            (m.mute_earbuds(True, False), 0xA2, b"\x01\x00"),
            (m.request_serial_numbers(), 0x29, b""),
            (m.set_touch_hold_option(2, 3), 0x92, b"\x02\x03"),
        ]
        for frame, msg_id, payload in cases:
            with self.subTest(msg=hex(msg_id)):
                self.assertEqual((frame.msg_id, frame.payload), (msg_id, payload))
                self.assertEqual(decode(frame.encode()), frame)

    def test_noise_cycle_payload_and_validation(self):
        both = NoiseCycle(anc=True, ambient=True, off=False)
        self.assertEqual(m.set_noise_cycle(both, both).payload, h("01 01 00 01 01 00"))
        with self.assertRaises(ValueError):
            m.set_noise_cycle(NoiseCycle(True, False, False), both)

    def test_ambient_customization_payload(self):
        value = AmbientCustomization(True, 1, 2, 2, True, 1)
        self.assertEqual(m.set_ambient_customization(value).payload, h("01 01 02 02 01 01"))

    def test_rejects_invalid_values(self):
        for call in (lambda: m.set_preset(6), lambda: m.set_noise_control(3),
                     lambda: m.set_balance(33), lambda: m.set_touch_hold_option(0, 2)):
            with self.assertRaises(ValueError):
                call()


class DecodeTest(unittest.TestCase):
    def test_roundtrip(self):
        for text in [*PRESET_FRAMES.values(), *NOISE_FRAMES.values(), EXTENDED_STATUS_REPLY,
                     TOUCH_TRIPLE_OFF_FRAME, BALANCE_10_FRAME]:
            with self.subTest(frame=text):
                self.assertEqual(decode(h(text)).encode(), h(text))

    def test_errors(self):
        with self.assertRaises(FrameError):
            decode(h("FD 04 00 86 01 1F A2 DD"))
        with self.assertRaises(FrameError):
            decode(h("FE 04 00 86 01 1F A1 DD"))

    def test_reader_split_garbage_and_corruption(self):
        corrupt = bytearray(h(PRESET_FRAMES[4]))
        corrupt[4] ^= 0xFF
        stream = h("00 11 DD") + bytes(corrupt) + h(PRESET_FRAMES[3]) + h(NOISE_FRAMES[1])
        reader = FrameReader()
        frames = reader.feed(stream[:-3]) + reader.feed(stream[-3:])
        self.assertEqual([(f.msg_id, f.payload) for f in frames], [(0x86, b"\x03"), (0x78, b"\x01")])
        self.assertTrue(reader.errors)


class RealDeviceTest(unittest.TestCase):
    def test_extended_status(self):
        session = Session()
        update = session.feed(device_frame(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS))
        self.assertEqual(update.replies, [h(EXTENDED_STATUS_REPLY)])
        s = session.state
        self.assertTrue(s.ready)
        self.assertEqual((s.battery_left, s.battery_right, s.battery_case), (100, 100, None))
        self.assertEqual((s.wearing_left, s.wearing_right), (True, True))
        self.assertTrue(s.coupled)
        self.assertFalse(s.primary_left)
        self.assertFalse(s.game_mode)
        self.assertEqual(s.equalizer, Preset.NORMAL)
        self.assertEqual(s.touch, ALL_ON)
        self.assertEqual((s.touch_hold_left, s.touch_hold_right), (2, 2))
        self.assertEqual(s.noise_control, NoiseControl.AMBIENT)
        cycle = NoiseCycle(anc=True, ambient=True, off=False)
        self.assertEqual((s.noise_cycle_first, s.noise_cycle_second), (cycle, cycle))
        self.assertEqual(s.balance, 16)
        self.assertFalse(s.anc_with_one_earbud)
        self.assertEqual(s.ambient, AmbientCustomization(True, 1, 1, 2, True, 1))
        self.assertFalse(s.extra_high_ambient)
        self.assertFalse(s.ambient_during_calls)
        self.assertTrue(s.in_ear_detection)
        self.assertEqual((s.charging_left, s.charging_right, s.charging_case), (False, False, False))

    def test_status_updated_and_host_ack(self):
        session = Session()
        update = session.feed(device_frame(MsgId.STATUS_UPDATED, REAL_STATUS_IN_EAR))
        self.assertEqual(update.replies, [m.host_ack(0x60).encode()])
        s = session.state
        self.assertEqual((s.battery_left, s.battery_right, s.battery_case), (100, 100, None))
        self.assertEqual((s.wearing_left, s.wearing_right), (True, True))
        session.feed(device_frame(MsgId.STATUS_UPDATED, REAL_STATUS_OUT_OF_EAR))
        self.assertEqual((session.state.wearing_left, session.state.placement_left), (False, 2))

    def test_version_info_long(self):
        session = Session()
        update = session.feed(device_frame(MsgId.VERSION_INFO_LONG, REAL_VERSION_INFO_LONG))
        self.assertTrue(update.info_changed)
        self.assertEqual(update.replies, [m.host_ack(0x68).encode()])
        info = session.info
        self.assertEqual((info.firmware_left, info.firmware_right), ("R410XXU0AYI2", "R410XXU0AYI2"))
        self.assertEqual((info.hw_left, info.touch_fw_left), (0x10, 1))

    def test_cradle_serial(self):
        session = Session()
        session.feed(device_frame(MsgId.CRADLE_SERIAL_NUMBER, CRADLE_SERIAL))
        self.assertEqual((session.info.case_firmware, session.info.case_serial), ("QR410CYCA", "R0AA0000000"))

    def test_serial_numbers(self):
        session = Session()
        session.feed(device_frame(MsgId.DEBUG_SERIAL_NUMBER, b"RFAKE000001" + b"RFAKE000002"))
        self.assertEqual((session.info.serial_left, session.info.serial_right), ("RFAKE000001", "RFAKE000002"))

    def test_acks_with_response_flag(self):
        session = Session()
        stream = b"".join(
            device_frame(MsgId.UNIVERSAL_ACK, p, response=True)
            for p in (REAL_ACK_EQ_BASS, REAL_ACK_NOISE_ANC, REAL_ACK_TOUCH_TRIPLE_OFF)
        )
        update = session.feed(stream)
        self.assertEqual([a.msg_id for a in update.acks], [0x86, 0x78, 0x90])
        self.assertEqual(update.replies, [])
        s = session.state
        self.assertEqual((s.equalizer, s.noise_control), (Preset.BASS_BOOST, NoiseControl.ANC))
        self.assertFalse(s.touch.triple_tap)

    def test_acks_seen_on_real_device_for_other_settings(self):
        # Acks observados no SM-R410 (2026-10-14) para IDs sem case próprio no APK.
        session = Session()
        stream = b"".join(
            device_frame(MsgId.UNIVERSAL_ACK, h(p), response=True)
            for p in ("8F 0A", "6F 01", "8B 01", "6E 01", "85 01", "92 03 03", "79 01 01 01 01 01 01")
        )
        session.feed(stream)
        s = session.state
        self.assertEqual((s.balance, s.anc_with_one_earbud, s.ambient_during_calls), (10, True, True))
        self.assertEqual((s.in_ear_detection, s.game_mode), (False, True))
        self.assertEqual((s.touch_hold_left, s.touch_hold_right), (3, 3))
        self.assertEqual(s.noise_cycle_first, NoiseCycle(True, True, True))

    def test_noise_update_and_fit_result(self):
        session = Session()
        update = session.feed(
            device_frame(MsgId.NOISE_CONTROLS_UPDATE, h("01 11"))
            + device_frame(MsgId.FIT_TEST_RESULT, h("01 02"))
        )
        self.assertEqual(session.state.noise_control, NoiseControl.ANC)
        self.assertEqual([(r.left, r.right) for r in update.fit_results], [(1, 2)])

    def test_does_not_reply_to_responses(self):
        session = Session()
        update = session.feed(h(EXTENDED_STATUS_REPLY))
        self.assertEqual(update.replies, [])
        self.assertFalse(session.state.ready)

    def test_basic_layout_reads_only_battery(self):
        session = Session(BASIC_LAYOUT)
        session.feed(device_frame(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS))
        self.assertEqual(session.state.battery_left, 100)
        self.assertIsNone(session.state.equalizer)

    def test_truncated_extended_status(self):
        session = Session()
        session.feed(device_frame(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS[:13]))
        self.assertEqual(session.state.noise_control, NoiseControl.AMBIENT)
        self.assertIsNone(session.state.balance)


class ModelTest(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(detect_model("Galaxy Buds Core").key, "core")
        self.assertTrue(detect_model("Galaxy Buds Core").validated)
        self.assertEqual(detect_model("Galaxy Buds3 Pro").key, "buds3_pro")
        self.assertEqual(detect_model("Galaxy Buds3").key, "buds3")
        self.assertEqual(detect_model("Galaxy Buds2 Pro").key, "buds2_pro")
        self.assertFalse(detect_model("Galaxy Buds").supported)
        self.assertEqual(detect_model("Fone qualquer").key, "unknown")

    def test_capabilities(self):
        core = detect_model("Galaxy Buds Core")
        self.assertTrue(all(core.has(cap) for cap in Cap))
        buds2 = detect_model("Galaxy Buds2")
        self.assertFalse(buds2.validated)
        self.assertFalse(buds2.has(Cap.FIND_MY_EARBUDS))


if __name__ == "__main__":
    unittest.main()
