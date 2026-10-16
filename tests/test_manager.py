"""Gerenciador de vários fones (transporte simulado) e troca de tema."""

import tempfile
import unittest
from pathlib import Path

from frames import REAL_EXTENDED_STATUS, h
from test_services import FakeTransport

from budsstudio.protocol import Frame, MsgId
from budsstudio.services.config import Config
from budsstudio.services.manager import DeviceManager, SelectedDevice
from budsstudio.transport.bluez import BluezDevice

CORE_A = BluezDevice("/org/bluez/hci0/dev_A", "AA:AA:AA:AA:AA:01", "Fone da sala", True, "Galaxy Buds Core")
CORE_B = BluezDevice("/org/bluez/hci0/dev_B", "BB:BB:BB:BB:BB:02", "Fone do trabalho", True, "Galaxy Buds Core")
BUDS2 = BluezDevice("/org/bluez/hci0/dev_C", "CC:CC:CC:CC:CC:03", "Buds2", True, "Galaxy Buds2")


def status_with_battery(left: int, right: int) -> bytes:
    payload = bytearray(REAL_EXTENDED_STATUS)
    payload[2], payload[3] = left, right
    return Frame(MsgId.EXTENDED_STATUS_UPDATED, bytes(payload)).encode()


def manager_with(*devices):
    transports = []

    def factory():
        t = FakeTransport()
        transports.append(t)
        return t

    manager = DeviceManager(lister=lambda: list(devices), transport_factory=factory)
    for dev in devices:
        manager.add(dev)
    return manager, transports


class ManagerTest(unittest.TestCase):
    def test_each_device_has_its_own_connection_and_state(self):
        manager, (ta, tb) = manager_with(CORE_A, CORE_B)
        ta.on_data(status_with_battery(80, 81))
        tb.on_data(status_with_battery(30, 31))
        a, b = manager.get(CORE_A.address), manager.get(CORE_B.address)
        self.assertTrue(a.connected and b.connected)
        self.assertEqual((a.state.battery_left, b.state.battery_left), (80, 30))
        a.set_preset(1)
        self.assertEqual([f.msg_id for f in ta.sent_frames()][-1], 0x86)
        self.assertNotIn(0x86, [f.msg_id for f in tb.sent_frames()])

    def test_switching_keeps_other_devices_connected(self):
        manager, (ta, tb) = manager_with(CORE_A, CORE_B)
        self.assertEqual(manager.selected_address, CORE_A.address)
        manager.select(CORE_B.address)
        self.assertEqual(manager.selected.device.address, CORE_B.address)
        self.assertTrue(manager.get(CORE_A.address).connected)
        self.assertEqual(len(manager.connected_services()), 2)

    def test_selected_proxy_follows_selection_and_relays_signals(self):
        manager, (ta, tb) = manager_with(CORE_A, CORE_B)
        proxy = SelectedDevice(manager)
        events = []
        proxy.connect("state-changed", lambda *_: events.append("state"))
        ta.on_data(status_with_battery(70, 71))
        tb.on_data(status_with_battery(20, 21))
        self.assertEqual(proxy.state.battery_left, 70)
        events.clear()
        manager.select(CORE_B.address)
        self.assertEqual(proxy.state.battery_left, 20)
        self.assertIn("state", events)
        # O fone antigo não deve mais disparar eventos no proxy.
        events.clear()
        ta.on_data(status_with_battery(60, 61))
        self.assertEqual(events, [])
        tb.on_data(status_with_battery(19, 21))
        self.assertEqual(events, ["state"])
        proxy.set_preset(4)
        self.assertEqual(tb.sent_frames()[-1].payload, h("04"))

    def test_forget_disconnects_only_that_device(self):
        manager, (ta, tb) = manager_with(CORE_A, CORE_B)
        manager.forget(CORE_A.address)
        self.assertIsNone(manager.get(CORE_A.address))
        self.assertEqual(manager.selected_address, CORE_B.address)
        self.assertTrue(manager.get(CORE_B.address).connected)

    def test_find_by_name_or_address_and_capabilities_per_model(self):
        manager, _ = manager_with(CORE_A, BUDS2)
        self.assertIs(manager.find("fone da sala"), manager.get(CORE_A.address))
        self.assertIs(manager.find("cc:cc:cc:cc:cc:03"), manager.get(BUDS2.address))
        self.assertTrue(manager.get(CORE_A.address).model.validated)
        self.assertFalse(manager.get(BUDS2.address).model.validated)
        self.assertIsNone(manager.find("outro"))

    def test_no_device_selected_is_safe(self):
        manager = DeviceManager(lister=lambda: [], transport_factory=FakeTransport)
        proxy = SelectedDevice(manager)
        self.assertFalse(proxy.connected)
        self.assertIsNone(proxy.state.battery_left)


class ConfigMigrationTest(unittest.TestCase):
    def test_single_device_config_becomes_device_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"last_device": "AA:AA:AA:AA:AA:01", "last_preset": 2}')
            config = Config.load(path)
            self.assertEqual(config.devices, ["AA:AA:AA:AA:AA:01"])
            self.assertEqual(config.device_presets, {"AA:AA:AA:AA:AA:01": 2})
            self.assertEqual(config.theme, "system")


class ThemeTest(unittest.TestCase):
    def test_theme_maps_to_color_scheme(self):
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw

        from budsstudio.ui.style import color_scheme_for

        self.assertEqual(color_scheme_for("light"), Adw.ColorScheme.FORCE_LIGHT)
        self.assertEqual(color_scheme_for("dark"), Adw.ColorScheme.FORCE_DARK)
        self.assertEqual(color_scheme_for("system"), Adw.ColorScheme.DEFAULT)
        self.assertEqual(color_scheme_for("qualquer"), Adw.ColorScheme.DEFAULT)

    def test_invalid_theme_in_config_falls_back_to_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"theme": "roxo"}')
            self.assertEqual(Config.load(path).theme, "system")
            Config(theme="dark").save(path)
            self.assertEqual(Config.load(path).theme, "dark")


if __name__ == "__main__":
    unittest.main()


class TransportDuplicateConnectTest(unittest.TestCase):
    """Regressão: um segundo connect() para o mesmo fone durante a conexão não pode reiniciá-la
    (isso desregistrava o Profile1 no meio do ConnectProfile e o BlueZ respondia
    br-connection-aborted-by-local)."""

    def test_second_connect_is_ignored(self):
        from unittest import mock

        from budsstudio.transport import bluez, connection

        calls = {"connect_profile": 0, "remove": 0}

        class FakeProfile:
            def add(self, *a):
                pass

            def remove(self, *a):
                calls["remove"] += 1

        with mock.patch.object(bluez, "system_bus", lambda: object()), \
             mock.patch.object(bluez.RfcommProfile, "shared", classmethod(lambda cls, bus: FakeProfile())), \
             mock.patch.object(bluez, "watch_device", lambda *a: 1), \
             mock.patch.object(bluez, "connect_profile", lambda *a: calls.__setitem__("connect_profile", calls["connect_profile"] + 1)):
            transport = connection.BluezTransport()
            transport.connect(CORE_A)
            transport.connect(CORE_A)
        self.assertEqual(calls["connect_profile"], 1)
        self.assertEqual(calls["remove"], 0)
        self.assertEqual(transport.state.value, "connecting")
