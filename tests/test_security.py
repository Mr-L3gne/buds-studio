"""node.name vindo do PipeWire nunca é interpolado sem validação (config do EQ e pw-metadata)."""

import copy
import json
import unittest

import frames  # noqa: F401  (põe src/ no sys.path)
import test_services

from budsstudio.services import pipewire as pw
from budsstudio.services.audio import parse_card
from budsstudio.services.system_eq import SystemEqService, _json_name, build_config

GOOD = "bluez_output.5C_5E_0A_64_00_C1.1"
EVIL = [
    'bluez_output.5C_5E_0A_64_00_C1.1" }] context.modules = [ { name = "x',
    "bluez_output.5C}{_00.1",
    'x", "evil": "1',
    "bluez_output.5C_5E_0A_64_00_C1.1\n",
    "alsa_output.pci-0000_00_1f.3.analog-stereo",
    "",
    None,
]


class SinkNameTest(unittest.TestCase):
    def test_valid_names(self):
        self.assertTrue(pw.valid_bluez_sink(GOOD))
        self.assertTrue(pw.valid_bluez_sink("bluez_output.5C_5E_0A_64_00_C1"))
        for name in EVIL:
            self.assertFalse(pw.valid_bluez_sink(name), name)

    def test_config_rejects_quotes_and_braces(self):
        for name in EVIL:
            with self.assertRaises(ValueError):
                build_config([0.0] * 10, name, "Buds Studio EQ")

    def test_service_never_targets_invalid_name(self):
        eq = SystemEqService()
        for name in EVIL:
            eq.set_target_sink(name)
            self.assertIsNone(eq.target_sink)

    def test_pw_metadata_value_is_real_json(self):
        value = pw.sink_json('a"b}{c')
        self.assertEqual(json.loads(value), {"name": 'a"b}{c'})
        self.assertEqual(_json_name(pw.sink_json(GOOD)), GOOD)
        self.assertIsNone(_json_name("{not json"))
        self.assertIsNone(_json_name('["name"]'))

    def test_card_rejects_foreign_or_malformed_sink(self):
        objects = copy.deepcopy(test_services.PipeWireParsingTest.OBJECTS)
        node = objects[1]["info"]["props"]
        node["node.name"] = EVIL[0]
        self.assertIsNone(parse_card(objects, "5C:5E:0A:64:00:C1").sink_node)
        node["node.name"] = GOOD
        node["api.bluez5.address"] = "AA:BB:CC:DD:EE:FF"  # mesmo device.id, outro fone
        self.assertIsNone(parse_card(objects, "5C:5E:0A:64:00:C1").sink_node)
        node["api.bluez5.address"] = "5c:5e:0a:64:00:c1"
        self.assertEqual(parse_card(objects, "5C:5E:0A:64:00:C1").sink_node, GOOD)
        del node["api.bluez5.address"]
        node["device.api"] = "alsa"
        self.assertIsNone(parse_card(objects, "5C:5E:0A:64:00:C1").sink_node)


if __name__ == "__main__":
    unittest.main()
