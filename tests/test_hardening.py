"""Endurecimento: arquivos privados e atômicos, entradas hostis e limites da CLI, e o EQ do computador."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import frames  # noqa: F401  (põe src/ no sys.path)

from budsstudio.cli import MAX_ARG_LENGTH, MAX_ARGS, CliError, build_parser, check_argv, is_action
from budsstudio.services.config import SYSTEM_EQ_BANDS_HZ, Config
from budsstudio.services.eq_curves import (
    SYSTEM_EQ_PRESETS, headroom_db, preamp_mult, preset_for, preset_gains,
)
from budsstudio.services.fsutil import MAX_JSON_BYTES, private_dir, read_json, write_private
from budsstudio.services.profiles import MAX_NAME_LENGTH, MAX_PROFILES, Profile, ProfileError, ProfileStore
from budsstudio.services import pipewire as pw
from budsstudio.services.system_eq import PREAMP, SystemEqService, build_config

SINK = "bluez_output.5C_5E_0A_64_00_C1.1"
DEEP = "[" * 100_000 + "]" * 100_000  # estoura a pilha do json.loads


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class PrivateFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_private_is_0600_and_leaves_no_temp_file(self):
        target = self.dir / "a.json"
        write_private(target, "um")
        write_private(target, "dois")  # substitui o existente
        self.assertEqual(target.read_text(), "dois")
        self.assertEqual(mode(target), 0o600)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.json"])

    def test_failed_write_keeps_old_file_and_cleans_up(self):
        target = self.dir / "a.json"
        write_private(target, "antigo")
        with self.assertRaises(UnicodeEncodeError):
            write_private(target, "\ud800")  # surrogate solto não vira UTF-8
        self.assertEqual(target.read_text(), "antigo")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.json"])

    def test_exported_profiles_follow_the_umask_not_0600(self):
        store = ProfileStore(self.dir / "profiles.json")
        store.put(Profile(name="Música", preset=1))
        old = os.umask(0o022)
        try:
            store.export(self.dir / "shared.json")
        finally:
            os.umask(old)
        self.assertEqual(mode(self.dir / "shared.json"), 0o644)
        self.assertEqual(ProfileStore(self.dir / "shared.json").profiles[0].name, "Música")

    def test_private_dir_is_0700(self):
        created = private_dir(self.dir / "x" / "y")
        self.assertEqual(mode(created), 0o700)

    def test_config_and_profiles_are_saved_private(self):
        Config().save(self.dir / "cfg" / "config.json")
        self.assertEqual(mode(self.dir / "cfg" / "config.json"), 0o600)
        store = ProfileStore(self.dir / "cfg" / "profiles.json")
        store.put(Profile(name="Música", preset=1))
        self.assertEqual(mode(self.dir / "cfg" / "profiles.json"), 0o600)


class HostileJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_read_json_rejects_huge_and_deep_files(self):
        with self.assertRaises(ValueError):
            read_json(self.write("big.json", " " * (MAX_JSON_BYTES + 1)))
        with self.assertRaises(ValueError):
            read_json(self.write("deep.json", DEEP))
        (self.dir / "bin.json").write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(ValueError):
            read_json(self.dir / "bin.json")

    def test_config_falls_back_to_defaults(self):
        for text in (DEEP, " " * (MAX_JSON_BYTES + 1), "[]", "nada"):
            path = self.write("config.json", text)
            self.assertEqual(Config.load(path), Config(), text[:10])

    def test_import_rejects_deep_and_huge_files(self):
        store = ProfileStore(self.dir / "profiles.json")
        for text in (DEEP, " " * (MAX_JSON_BYTES + 1)):
            with self.assertRaises(ProfileError):
                store.import_file(self.write("in.json", text))
        self.assertEqual(store.profiles, [])

    def test_profile_names_lose_control_characters_and_are_capped(self):
        profile = Profile.from_dict({"name": "  Mú\nsi\x1b[31mca‮  ", "preset": 1})
        self.assertEqual(profile.name, "Mú" + "si[31mca")
        with self.assertRaises(ProfileError):
            Profile.from_dict({"name": "x" * (MAX_NAME_LENGTH + 1)})
        with self.assertRaises(ProfileError):
            Profile.from_dict({"name": "\n\t "})

    def test_booleans_are_not_numbers_in_profiles(self):
        for key in ("preset", "noise_control", "balance"):
            with self.assertRaises(ProfileError, msg=key):
                Profile.from_dict({"name": "a", key: True})
        with self.assertRaises(ProfileError):
            Profile.from_dict({"name": "a", "system_eq_gains": [True] * len(SYSTEM_EQ_BANDS_HZ)})

    def test_profile_count_is_capped_on_import_and_save(self):
        many = {"format": "buds-studio-profiles", "version": 1,
                "profiles": [{"name": f"p{i}"} for i in range(MAX_PROFILES + 1)]}
        store = ProfileStore(self.dir / "profiles.json")
        with self.assertRaises(ProfileError):
            store.import_file(self.write("many.json", json.dumps(many)))
        for i in range(MAX_PROFILES):
            store.profiles.append(Profile(name=f"q{i}"))
        with self.assertRaises(ProfileError):
            store.put(Profile(name="uma a mais"))
        # importar mais um perfil novo também passa do limite e não deixa o arquivo pela metade
        extra = {"format": "buds-studio-profiles", "version": 1, "profiles": [{"name": "outro"}]}
        with self.assertRaises(ProfileError):
            store.import_file(self.write("extra.json", json.dumps(extra)))
        self.assertEqual(len(store.profiles), MAX_PROFILES)


class CliLimitsTest(unittest.TestCase):
    def test_argv_limits(self):
        check_argv(["--status"] * MAX_ARGS)
        with self.assertRaises(CliError):
            check_argv(["--status"] * (MAX_ARGS + 1))
        with self.assertRaises(CliError):
            check_argv(["x" * (MAX_ARG_LENGTH + 1)])
        with self.assertRaises(CliError):
            check_argv([1])

    def test_timeout_is_bounded(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["--status", "--timeout", "30"]).timeout, 30.0)
        for bad in ("0", "-1", "nan", "inf", "100000", "abc"):
            with self.assertRaises(CliError, msg=bad):
                parser.parse_args(["--status", "--timeout", bad])

    def test_system_eq_preset_option(self):
        parser = build_parser()
        args = parser.parse_args(["--system-eq-preset", "bass"])
        self.assertTrue(is_action(args))
        self.assertEqual(args.system_eq_preset, "bass")
        with self.assertRaises(CliError):
            parser.parse_args(["--system-eq-preset", "inexistente"])


class SystemEqCurvesTest(unittest.TestCase):
    def test_cut_only_curves_need_no_headroom(self):
        self.assertEqual(headroom_db([0.0] * 10), 0.0)
        self.assertEqual(headroom_db([-6.0] * 10), 0.0)
        self.assertEqual(preamp_mult([-3.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 1.0)

    def test_headroom_covers_the_real_peak(self):
        single = [0.0] * 10
        single[5] = 6.0  # +6 dB em 1 kHz
        self.assertAlmostEqual(headroom_db(single), 6.0, delta=0.1)
        # bandas vizinhas se somam: o pico passa do maior ganho individual
        bass = list(preset_gains("bass"))
        self.assertGreater(headroom_db(bass), max(bass))
        # e a compensação mantém o pico em ~0 dB
        self.assertAlmostEqual(20 * __import__("math").log10(preamp_mult(bass)), -headroom_db(bass), delta=0.01)
        self.assertEqual(preamp_mult(bass, enabled=False), 1.0)

    def test_presets_have_ten_bands_in_range_and_are_recognised(self):
        for name, values in SYSTEM_EQ_PRESETS.items():
            self.assertEqual(len(values), len(SYSTEM_EQ_BANDS_HZ), name)
            self.assertTrue(all(abs(v) <= 12 for v in values), name)
            self.assertEqual(preset_for(preset_gains(name)), name)
        self.assertIsNone(preset_for([1.0] * 10))
        self.assertIsNone(preset_for([0.0] * 9))
        self.assertIsNone(preset_gains("nao-existe"))

    def test_config_has_a_preamp_wired_in_front_of_the_bands(self):
        gains = preset_gains("bass")
        conf = build_config(gains, SINK, "Buds Studio EQ")
        self.assertIn(f'name = {PREAMP} label = linear', conf)
        self.assertIn(f'"Mult" = {preamp_mult(gains):.4f}', conf)
        self.assertIn(f'{{ output = "{PREAMP}:Out" input = "band1:In" }}', conf)
        self.assertEqual(conf.count("input ="), len(SYSTEM_EQ_BANDS_HZ))  # preamp→1, 1→2 … 9→10
        off = build_config(gains, SINK, "Buds Studio EQ", headroom=False)
        self.assertIn('"Mult" = 1.0000', off)


class SystemEqLiveUpdateTest(unittest.TestCase):
    def test_live_push_carries_gains_and_preamp(self):
        calls = []
        real_run = pw.run
        pw.run = lambda argv, *a, **k: calls.append(argv)
        try:
            eq = SystemEqService()
            eq.node_id = 42
            eq.set_gains(preset_gains("bass"))
            eq._push_gains()
            self.assertEqual(calls[-1][:4], ["pw-cli", "set-param", "42", "Props"])
            self.assertIn(f'"{PREAMP}:Mult" {preamp_mult(preset_gains("bass")):.4f}', calls[-1][4])
            self.assertIn('"band1:Gain" 6.00', calls[-1][4])
            eq.headroom = False  # sem compensação: o multiplicador volta a 1
            eq._push_gains()
            self.assertIn(f'"{PREAMP}:Mult" 1.0000', calls[-1][4])
        finally:
            pw.run = real_run


if __name__ == "__main__":
    unittest.main()
