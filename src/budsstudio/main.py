"""Ponto de entrada: `buds-studio` (janela) ou `buds-studio --status` etc. (CLI)."""

from __future__ import annotations

import sys

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


def _forward_to_running_instance(argv: list[str]) -> int | None:
    """Se o app já está aberto e o pedido é um comando da CLI, executa nele via D-Bus.

    Devolve o código de saída, ou None se não houver instância aberta (ou não for comando).
    """
    from gi.repository import Gio, GLib

    from . import APP_ID
    from .cli import CliError, build_parser, is_action
    from .ui.app import CLI_INTERFACE, CLI_PATH

    try:
        args = build_parser().parse_args(argv)
    except CliError:
        return None
    if not is_action(args):
        return None
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        (owned,) = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None,
        ).unpack()
        if not owned:
            return None
        timeout_ms = int((args.timeout + 40) * 1000)
        code, out, err = bus.call_sync(
            APP_ID, CLI_PATH, CLI_INTERFACE, "Run", GLib.Variant("(as)", (argv,)),
            GLib.VariantType("(iss)"), Gio.DBusCallFlags.NONE, timeout_ms, None,
        ).unpack()
    except GLib.Error:
        return None
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    from . import i18n
    from .services.config import Config

    argv = sys.argv if argv is None else argv
    config = Config.load()
    i18n.setup(config.language)
    from . import APP_NAME, VERSION
    from .cli import CliError, build_parser

    parser = build_parser()
    try:
        args = parser.parse_args(argv[1:])
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.help:
        print(parser.format_help())
        return 0
    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return 0
    forwarded = _forward_to_running_instance(argv[1:])
    if forwarded is not None:
        return forwarded
    from .ui.app import run

    return run(argv, config)


if __name__ == "__main__":
    sys.exit(main())
