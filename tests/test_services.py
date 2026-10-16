"""Testes de services/ com transporte simulado (sem Bluetooth)."""

import json
import tempfile
import unittest
from pathlib import Path

from frames import REAL_EXTENDED_STATUS, REAL_VERSION_INFO_LONG, h

from budsstudio.protocol import Frame, MsgId, NoiseCycle, decode
from budsstudio.services.audio import parse_card, pick_profile, recording_streams
from budsstudio.services.config import Config
from budsstudio.services.device import CommandError, DeviceService
from budsstudio.services.profiles import Profile, ProfileError, ProfileStore, apply_profile
from budsstudio.services.system_eq import build_config
from budsstudio.transport.bluez import BluezDevice
from budsstudio.transport.connection import ConnectionState

CORE = BluezDevice("/org/bluez/hci0/dev_X", "5C:5E:0A:64:00:C1", "Meus fones", True, "Galaxy Buds Core")
BUDS2 = BluezDevice("/org/bluez/hci0/dev_Y", "AA:BB:CC:DD:EE:FF", "Buds2", True, "Galaxy Buds2")


class FakeTransport:
    def __init__(self):
        self.on_state = lambda *_: None
        self.on_data = lambda _d: None
        self.state = ConnectionState.DISCONNECTED
        self.auto_reconnect = True
        self.sent: list[bytes] = []

    def devices(self):
        return [CORE]

    def connect(self, device, channel=None):
        self._set(ConnectionState.CONNECTING)
        self._set(ConnectionState.CONNECTED)

    def disconnect(self):
        self._set(ConnectionState.DISCONNECTED)

    def shutdown(self):
        self.state = ConnectionState.DISCONNECTED

    def send(self, data):
        self.sent.append(bytes(data))

    def _set(self, state):
        self.state = state
        self.on_state(state, None)

    # helpers
    def receive(self, msg_id, payload, response=False):
        self.on_data(Frame(msg_id, payload, response=response).encode())

    def sent_frames(self):
        return [decode(d) for d in self.sent]


def connected_service(device=CORE):
    transport = FakeTransport()
    service = DeviceService(transport)
    service.connect_device(device)
    return service, transport


class DeviceServiceTest(unittest.TestCase):
    def test_model_from_remote_name_not_alias(self):
        service, _ = connected_service()
        self.assertEqual(service.model.key, "core")

    def test_handshake_ready_and_serial_request(self):
        service, transport = connected_service()
        events = []
        service.connect("ready", lambda *_: events.append("ready"))
        transport.receive(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS)
        frames = transport.sent_frames()
        self.assertEqual([(f.msg_id, f.response) for f in frames], [(0x61, True), (0x29, False)])
        self.assertEqual(events, ["ready"])
        self.assertTrue(service.state.in_ear_detection)

    def test_info_from_version_message(self):
        service, transport = connected_service()
        transport.receive(MsgId.VERSION_INFO_LONG, REAL_VERSION_INFO_LONG)
        self.assertEqual(service.info.firmware_left, "R410XXU0AYI2")

    def test_commands_send_expected_frames(self):
        service, transport = connected_service()
        transport.receive(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS)
        transport.sent.clear()
        service.set_preset(1)
        service.set_noise_control(1)
        service.set_balance(10)
        service.set_touch_field("triple_tap", False)
        service.set_touch_hold_options(2, 3)
        cycle = NoiseCycle(True, False, True)
        service.set_noise_cycle(cycle, cycle)
        service.set_anc_with_one_earbud(True)
        service.set_ambient_during_calls(True)
        service.set_in_ear_detection(False)
        service.set_game_mode(True)
        service.set_ambient_volume(2, 0)
        got = [(f.msg_id, f.payload) for f in transport.sent_frames()]
        self.assertEqual(
            got,
            [
                (0x86, h("01")),
                (0x78, h("01")),
                (0x8F, h("0A")),
                (0x90, h("01 01 01 00 01 01 01")),
                (0x92, h("02 03")),
                (0x79, h("01 00 01 01 00 01")),
                (0x6F, h("01")),
                (0x8B, h("01")),
                (0x6E, h("01")),
                (0x85, h("01")),
                (0x82, h("01 02 00 02 01 01")),
            ],
        )
        self.assertEqual(service.state.balance, 10)

    def test_extra_high_ambient_on_and_off(self):
        service, transport = connected_service()
        transport.receive(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS)
        transport.sent.clear()
        service.set_extra_high_ambient(True)
        service.set_extra_high_ambient(False)
        got = [(f.msg_id, f.payload) for f in transport.sent_frames()]
        self.assertEqual(
            got,
            [(0x96, h("01")), (0x82, h("01 04 04 02 01 01")), (0x96, h("00")), (0x82, h("01 01 01 02 01 01"))],
        )

    def test_find_my_earbuds_and_timeout_stop(self):
        service, transport = connected_service()
        service.find_start()
        service.set_find_mute(True, False)
        self.assertTrue(service.finding)
        service.find_stop()
        got = [(f.msg_id, f.payload) for f in transport.sent_frames()]
        self.assertEqual(got, [(0xA6, b""), (0xA2, h("01 00")), (0xA1, b"")])
        self.assertFalse(service.finding)

    def test_fit_test_needs_both_earbuds_and_stops_after_result(self):
        service, transport = connected_service()
        with self.assertRaises(CommandError):
            service.fit_test_start()
        transport.receive(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS)  # ambos no ouvido
        transport.sent.clear()
        results = []
        service.connect("fit-result", lambda _s, l, r: results.append((l, r)))
        service.fit_test_start()
        transport.receive(MsgId.FIT_TEST_RESULT, h("01 03"))
        got = [(f.msg_id, f.payload) for f in transport.sent_frames()]
        self.assertEqual(got, [(0x9D, h("01")), (0x9D, h("00"))])
        self.assertEqual(results, [(1, 3)])

    def test_experimental_model_hides_unsupported_commands(self):
        service, transport = connected_service(BUDS2)
        self.assertFalse(service.model.validated)
        with self.assertRaises(CommandError):
            service.find_start()
        service.set_preset(2)
        self.assertEqual(transport.sent_frames()[-1].msg_id, 0x86)

    def test_not_connected(self):
        service = DeviceService(FakeTransport())
        with self.assertRaises(CommandError):
            service.set_preset(0)


class ProfilesTest(unittest.TestCase):
    def test_store_roundtrip_export_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / "profiles.json")
            store.put(Profile("Música", preset=1, noise_control=1, balance=16))
            store.put(Profile("Chamada", preset=4, noise_control=2))
            store.put(Profile("música", preset=3))  # mesmo nome, substitui
            self.assertEqual([p.name for p in store.profiles], ["música", "Chamada"])
            export = Path(tmp) / "export.json"
            store.export(export)
            data = json.loads(export.read_text())
            self.assertEqual(data["format"], "buds-studio-profiles")
            other = ProfileStore(Path(tmp) / "other.json")
            self.assertEqual(other.import_file(export), ["música", "Chamada"])
            self.assertEqual(ProfileStore(Path(tmp) / "other.json").get("CHAMADA").preset, 4)

    def test_rejects_invalid(self):
        with self.assertRaises(ProfileError):
            Profile.from_dict({"name": "x", "preset": 9})
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"format": "outro"}')
            with self.assertRaises(ProfileError):
                ProfileStore(Path(tmp) / "p.json").import_file(bad)

    def test_apply(self):
        service, transport = connected_service()
        transport.sent.clear()
        skipped = apply_profile(Profile("x", preset=5, noise_control=0, game_mode=False), service)
        self.assertEqual(skipped, [])
        self.assertEqual([f.msg_id for f in transport.sent_frames()], [0x86, 0x78, 0x85])


class ConfigTest(unittest.TestCase):
    def test_roundtrip_and_sanitize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            Config(last_device="AA", last_preset=3, system_eq_gains=[20.0] * 10).save(path)
            loaded = Config.load(path)
            self.assertEqual((loaded.last_device, loaded.last_preset), ("AA", 3))
            self.assertEqual(loaded.system_eq_gains[0], 12.0)
            path.write_text('{"last_preset": 9, "language": "xx", "tray_icon": "sim"}')
            loaded = Config.load(path)
            self.assertIsNone(loaded.last_preset)
            self.assertEqual(loaded.language, "pt_BR")
            self.assertTrue(loaded.tray_icon)


class PipeWireParsingTest(unittest.TestCase):
    # Recorte real do `pw-dump` com o Galaxy Buds Core conectado.
    OBJECTS = [
        {
            "id": 87,
            "type": "PipeWire:Interface:Device",
            "info": {
                "props": {"api.bluez5.address": "5C:5E:0A:64:00:C1", "device.name": "bluez_card.5C_5E_0A_64_00_C1"},
                "params": {
                    "EnumProfile": [
                        {"index": 0, "name": "off", "description": "Off", "available": "yes"},
                        {"index": 3, "name": "headset-head-unit", "description": "Headset Head Unit (HSP/HFP)", "available": "yes"},
                        {"index": 5, "name": "a2dp-sink", "description": "High Fidelity Playback (A2DP Sink, codec SBC)", "available": "yes"},
                        {"index": 6, "name": "a2dp-sink-sbc_xq", "description": "A2DP SBC-XQ", "available": "yes"},
                        {"index": 261, "name": "headset-head-unit-msbc", "description": "HSP/HFP mSBC", "available": "yes"},
                    ],
                    "Profile": [{"index": 5, "name": "a2dp-sink"}],
                },
            },
        },
        {
            "id": 78,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"device.id": 87, "media.class": "Audio/Sink", "api.bluez5.codec": "sbc",
                               "node.name": "bluez_output.5C_5E_0A_64_00_C1.1"}},
        },
        {
            "id": 120,
            "type": "PipeWire:Interface:Node",
            "info": {"state": "running", "props": {"media.class": "Stream/Input/Audio", "application.name": "Discord"}},
        },
        {
            "id": 121,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": "Stream/Input/Audio", "stream.capture.sink": "true", "node.name": "peak"}},
        },
    ]

    def test_card(self):
        card = parse_card(self.OBJECTS, "5c:5e:0a:64:00:c1")
        self.assertEqual((card.device_id, card.current.name, card.codec), (87, "a2dp-sink", "sbc"))
        self.assertEqual(card.sink_node, "bluez_output.5C_5E_0A_64_00_C1.1")
        self.assertEqual(pick_profile(card, "hfp").name, "headset-head-unit-msbc")
        self.assertEqual(pick_profile(card, "a2dp").name, "a2dp-sink")
        self.assertIsNone(parse_card(self.OBJECTS, "00:00:00:00:00:00"))

    def test_recording_streams(self):
        self.assertEqual(recording_streams(self.OBJECTS), ["Discord"])

    def test_system_eq_config(self):
        conf = build_config([1.5] + [0.0] * 9, "bluez_output.X.1", "Buds Studio EQ")
        self.assertIn('label = bq_peaking control = { "Freq" = 31.0 "Q" = 1.41 "Gain" = 1.50 }', conf)
        self.assertIn('{ output = "band9:Out" input = "band10:In" }', conf)
        self.assertIn('target.object = "bluez_output.X.1"', conf)
        self.assertIn("media.category = Manager", conf)


if __name__ == "__main__":
    unittest.main()
