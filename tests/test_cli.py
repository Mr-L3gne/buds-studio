"""CLI sobre o gerenciador de vários fones, com transporte simulado."""

import time
import unittest

from gi.repository import GLib

from frames import REAL_EXTENDED_STATUS
from test_manager import CORE_A, CORE_B
from test_services import FakeTransport

from budsstudio.cli import build_parser
from budsstudio.cli.runner import CliRunner
from budsstudio.protocol import Frame, MsgId
from budsstudio.services.config import Config
from budsstudio.services.manager import DeviceManager, SelectedDevice


class FakeApp:
    """O mínimo da aplicação que a CLI usa (mesma lógica de ui/app.py)."""

    def __init__(self, devices):
        self.paired = list(devices)
        self.transports = {}

        def factory():
            t = FakeTransport()
            # Responde como o fone real: manda o status estendido ao conectar.
            original = t.connect

            def connect(device, channel=None):
                original(device, channel)
                t.on_data(Frame(MsgId.EXTENDED_STATUS_UPDATED, REAL_EXTENDED_STATUS).encode())

            t.connect = connect
            return t

        self.manager = DeviceManager(lister=lambda: self.paired, transport_factory=factory)
        self.device = SelectedDevice(self.manager)
        self.config = Config()
        self.profiles = None
        self.persistent = False

    def list_devices(self):
        return self.paired

    def find_device(self, query):
        q = query.casefold()
        return next((d for d in self.paired if q in (d.address.casefold(), d.name.casefold())), None)

    def connect_device_for_cli(self, device, channel):
        device = device or self.paired[0]
        service = self.manager.add(device, connect=False)
        self.manager.select(device.address)
        service.connect_device(device, channel)


def run_cli(app, argv, timeout_s=6.0):
    """Roda a CLI e o main loop do GLib até ela terminar (como no app)."""
    out, err, codes = [], [], []
    args = build_parser().parse_args(argv)
    CliRunner(app, args, out.append, err.append, codes.append).start()
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s
    while not codes and time.monotonic() < deadline:
        ctx.iteration(False)
        time.sleep(0.005)
    return codes, "\n".join(out), "\n".join(err)


class CliTest(unittest.TestCase):
    def test_status_by_device_name_with_first_selection(self):
        # Regressão: selecionar o primeiro fone reemite "disconnected" e não pode abortar a CLI.
        app = FakeApp([CORE_A, CORE_B])
        codes, out, err = run_cli(app, ["--status", "--device", "Fone do trabalho"])
        self.assertEqual(codes, [0], err)
        self.assertIn("Fone do trabalho", out)
        self.assertEqual(app.manager.selected_address, CORE_B.address)

    def test_preset_goes_to_the_chosen_device_only(self):
        app = FakeApp([CORE_A, CORE_B])
        run_cli(app, ["--status", "--device", CORE_A.address])
        run_cli(app, ["--preset", "bass", "--device", CORE_B.address])
        sent_b = [f.msg_id for f in app.manager.get(CORE_B.address).transport.sent_frames()]
        sent_a = [f.msg_id for f in app.manager.get(CORE_A.address).transport.sent_frames()]
        self.assertIn(0x86, sent_b)
        self.assertNotIn(0x86, sent_a)
        self.assertTrue(app.manager.get(CORE_A.address).connected)

    def test_unknown_device(self):
        app = FakeApp([CORE_A])
        codes, _out, err = run_cli(app, ["--status", "--device", "nenhum"])
        self.assertEqual(codes, [1])
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
