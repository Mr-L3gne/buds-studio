"""Linha de comando. Usa os mesmos services da interface.

Se o Buds Studio já estiver aberto (janela ou bandeja), o comando é executado nessa instância
(via GApplication), aproveitando a conexão existente. Senão, o processo conecta, executa e sai.
"""

from __future__ import annotations

import argparse
import json

from .. import APP_NAME, VERSION
from ..i18n import _
from ..protocol.messages import BALANCE_MAX, BALANCE_MIN, NOISE_KEYS, PRESET_KEYS

ACTION_KEYS = ("status", "info", "list", "preset", "anc", "profile", "profiles", "set", "find", "mute",
               "fit_test", "audio_profile", "system_eq")

SET_KEYS = {
    "balance": f"{BALANCE_MIN}-{BALANCE_MAX}",
    "anc-one-earbud": "on|off",
    "ambient-during-calls": "on|off",
    "in-ear-detection": "on|off",
    "game-mode": "on|off",
    "extra-high-ambient": "on|off",
    "ambient-volume": "L,R (0-2)",
    "touch-controls": "on|off",
    "gesture.tap": "on|off",
    "gesture.double-tap": "on|off",
    "gesture.triple-tap": "on|off",
    "gesture.touch-and-hold": "on|off",
    "gesture.calls-double-tap": "on|off",
    "gesture.calls-touch-and-hold": "on|off",
    "hold-left": "noise|volume",
    "hold-right": "noise|volume",
    "noise-cycle": "anc,ambient,off (2+)",
}


class CliError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # não chama sys.exit: a saída vai para o terminal certo
        raise CliError(f"{self.prog}: {message}")

    def exit(self, status=0, message=None):
        raise CliError(message or "")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="buds-studio",
        description=_("{app}: equalizer and settings for Galaxy Buds. Without options, opens the window.").format(app=APP_NAME),
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_("Keys for --set:") + "\n" + "\n".join(f"  {k:<30} {v}" for k, v in SET_KEYS.items()),
    )
    a = p.add_mutually_exclusive_group()
    a.add_argument("--status", action="store_true", help=_("show battery, equalizer and noise control"))
    a.add_argument("--info", action="store_true", help=_("show model, firmware and serial numbers"))
    a.add_argument("--list", action="store_true", help=_("list paired compatible earbuds"))
    a.add_argument("--preset", choices=list(PRESET_KEYS), help=_("apply an equalizer preset"))
    a.add_argument("--anc", choices=list(NOISE_KEYS), help=_("noise control mode"))
    a.add_argument("--profile", metavar=_("NAME"), help=_("apply a saved profile"))
    a.add_argument("--profiles", action="store_true", help=_("list saved profiles"))
    a.add_argument("--set", metavar=_("KEY=VALUE"), help=_("change another setting (see the list below)"))
    a.add_argument("--find", choices=["start", "stop"], help=_("make the earbuds ring (take them out of your ears!)"))
    a.add_argument("--mute", choices=["none", "left", "right", "both"], help=_("mute earbuds while finding"))
    a.add_argument("--fit-test", action="store_true", help=_("run the earbud fit test (wear both earbuds)"))
    a.add_argument("--audio-profile", choices=["a2dp", "hfp"], help=_("Bluetooth audio mode: music or headset"))
    a.add_argument("--system-eq", choices=["on", "off"], help=_("system equalizer (needs the app running)"))
    p.add_argument("--device", metavar=_("NAME|ADDRESS"), help=_("earbuds to use, by name or Bluetooth address"))
    p.add_argument("--channel", type=int, metavar="N", help=_("connect straight to this RFCOMM channel (diagnostics)"))
    p.add_argument("--timeout", type=float, default=15.0, help=_("seconds to wait (default: 15)"))
    p.add_argument("--json", action="store_true", help=_("JSON output for --status, --info and --list"))
    p.add_argument("--debug", action="store_true", help=_("print packets sent and received in hex"))
    p.add_argument("--background", action="store_true", help=_("start minimized in the background"))
    p.add_argument("--version", action="store_true", help=_("show the version"))
    p.add_argument("-h", "--help", action="store_true", help=_("show this help"))
    return p


def is_action(args) -> bool:
    return any(getattr(args, key) not in (None, False) for key in ACTION_KEYS)


def parse_on_off(value: str) -> bool:
    v = value.strip().lower()
    if v in ("on", "1", "true", "yes", "sim", "ligado"):
        return True
    if v in ("off", "0", "false", "no", "nao", "não", "desligado"):
        return False
    raise CliError(_("Use on or off, not “{value}”").format(value=value))


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


__all__ = ["CliError", "VERSION", "build_parser", "dumps", "is_action", "parse_on_off", "SET_KEYS"]
