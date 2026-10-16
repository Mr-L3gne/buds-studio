"""App ocioso: sinais só com mudança real, nada de pw-dump em paralelo, refresh não manda comando.

O teste de interface precisa de GTK ≥ 4.16 / libadwaita ≥ 1.7 e de um display; sem isso é pulado
(rode dentro do runtime do Flatpak, ver docs/TESTE-MANUAL.md).
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import frames  # noqa: F401  (põe src/ no sys.path)
from test_manager import CORE_A, manager_with, status_with_battery
from test_services import PipeWireParsingTest

from budsstudio.services import audio as audio_mod
from budsstudio.services.audio import AudioService
from budsstudio.services.system_eq import SystemEqService

OBJECTS = PipeWireParsingTest.OBJECTS


class FakeDump:
    """Substitui pw.dump: guarda os callbacks para o teste responder quando quiser."""

    def __init__(self):
        self.pending = []

    def __call__(self, on_done):
        self.pending.append(on_done)

    def answer(self, objects):
        pending, self.pending = self.pending, []
        for on_done in pending:
            on_done(objects, "")


def audio_service(dump):
    patcher = mock.patch.object(audio_mod.pw, "dump", dump)
    patcher.start()
    service = AudioService()
    service.available = True
    service.address = CORE_A.address
    return service, patcher


class AudioIdleTest(unittest.TestCase):
    def setUp(self):
        self.dump = FakeDump()
        self.audio, patcher = audio_service(self.dump)
        self.addCleanup(patcher.stop)
        self.changed = 0
        self.audio.connect("changed", lambda *_: setattr(self, "changed", self.changed + 1))

    def test_changed_only_when_state_changes(self):
        objects = [dict(o) for o in OBJECTS]
        objects[0] = dict(objects[0], info=dict(objects[0]["info"], props={"api.bluez5.address": CORE_A.address}))
        self.audio.refresh()
        self.dump.answer(objects)
        self.assertEqual(self.changed, 1)
        for _ in range(5):  # polls sem mudança
            self.audio.refresh()
            self.dump.answer(objects)
        self.assertEqual(self.changed, 1)
        self.audio.refresh()
        self.dump.answer(objects[:2])  # o Discord parou de gravar
        self.assertEqual(self.changed, 2)

    def test_no_parallel_dumps_and_every_caller_is_answered(self):
        done = []
        self.audio.refresh(lambda: done.append(1))
        self.audio.refresh(lambda: done.append(2))
        self.audio.refresh()
        self.assertEqual(len(self.dump.pending), 1)
        self.dump.answer(OBJECTS)
        self.assertEqual(sorted(done), [1, 2])


class SystemEqIdleTest(unittest.TestCase):
    def test_same_values_do_not_emit(self):
        eq = SystemEqService()
        changed = []
        eq.connect("changed", lambda *_: changed.append(1))
        eq.set_gains([0.0] * 10)
        eq.set_enabled(False)
        eq.set_target_sink(None)
        self.assertEqual(changed, [])
        eq.set_gains([1.0] + [0.0] * 9)
        self.assertEqual(changed, [1])


if __name__ == "__main__":
    unittest.main()
