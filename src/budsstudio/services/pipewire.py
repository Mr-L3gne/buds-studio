"""Acesso ao PipeWire pelas ferramentas `pw-dump`, `pw-cli` e `pw-metadata`, sem bloquear a UI.

No Flatpak, o WirePlumber dá a apps só leitura (`rx`), a não ser que o cliente declare
`media.category = Manager` (regra padrão de `50-default-access-config.lua`). O app usa um
`client.conf` próprio com essa propriedade, apontado por PIPEWIRE_CONFIG_DIR.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Callable

from gi.repository import Gio, GLib

from .. import APP_SLUG

_CLIENT_CONF = """# Gerado pelo Buds Studio: cliente PipeWire com permissão de gerenciador.
context.properties = {
    log.level = 0
    media.category = Manager
}
context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}
context.modules = [
    { name = libpipewire-module-rt args = { nice.level = -11 } flags = [ ifexists nofail ] }
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-metadata }
]
"""


# node.name da saída de um fone no PipeWire, ex.: bluez_output.5C_5E_0A_64_00_C1.1. Nada que venha
# do pw-dump vai para uma config ou para o pw-metadata sem bater com isto.
_BLUEZ_SINK = re.compile(r"^bluez_output\.[0-9A-Fa-f_]+(\.\d+)?$")


def valid_bluez_sink(name) -> bool:
    return isinstance(name, str) and _BLUEZ_SINK.fullmatch(name) is not None


def sink_json(node_name: str) -> str:
    """Valor de default.configured.audio.sink para o pw-metadata."""
    return json.dumps({"name": node_name})


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or GLib.get_user_runtime_dir()
    flatpak_id = os.environ.get("FLATPAK_ID")
    path = Path(base) / "app" / flatpak_id / APP_SLUG if flatpak_id else Path(base) / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def client_config_dir() -> Path:
    path = runtime_dir() / "pipewire"
    path.mkdir(parents=True, exist_ok=True)
    conf = path / "client.conf"
    if not conf.exists() or conf.read_text() != _CLIENT_CONF:
        conf.write_text(_CLIENT_CONF)
    return path


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def run(
    argv: list[str],
    on_done: Callable[[bool, str, str], None] | None = None,
    manager: bool = True,
) -> None:
    """Roda uma ferramenta do PipeWire de forma assíncrona. `on_done(ok, stdout, stderr)`."""
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    )
    if manager:
        launcher.setenv("PIPEWIRE_CONFIG_DIR", str(client_config_dir()), True)
    try:
        proc = launcher.spawnv(argv)
    except GLib.Error as exc:
        if on_done:
            on_done(False, "", exc.message)
        return

    def finished(p, result):
        try:
            _ok, out, err = p.communicate_utf8_finish(result)
        except GLib.Error as exc:
            if on_done:
                on_done(False, "", exc.message)
            return
        ok = p.get_successful() and "error" not in (err or "").lower()
        if on_done:
            on_done(ok, out or "", err or "")

    proc.communicate_utf8_async(None, None, finished)


def dump(on_done: Callable[[list | None, str], None]) -> None:
    def parsed(ok: bool, out: str, err: str) -> None:
        if not ok and not out:
            on_done(None, err)
            return
        try:
            on_done(json.loads(out), "")
        except ValueError as exc:
            on_done(None, str(exc))

    run(["pw-dump"], parsed, manager=False)


def props_of(obj: dict) -> dict:
    return ((obj.get("info") or {}).get("props")) or {}


def params_of(obj: dict) -> dict:
    return ((obj.get("info") or {}).get("params")) or {}
