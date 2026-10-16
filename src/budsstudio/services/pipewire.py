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


class NodeMonitor:
    """Avisa (`on_change`) quando um nó do PipeWire aparece, muda ou some, lendo o `pw-mon`.

    Só nós contam: o pw-dump/pw-cli do próprio app criam objetos Client, não Node, então não há
    realimentação. Os avisos em rajada viram um só (`debounce_ms`). `on_exit` é chamado se o
    pw-mon terminar sozinho.
    """

    _EVENTS = ("added:", "changed:", "removed:")

    def __init__(self, on_change: Callable[[], None], on_exit: Callable[[], None] = lambda: None,
                 debounce_ms: int = 300) -> None:
        self._on_change = on_change
        self._on_exit = on_exit
        self._debounce_ms = debounce_ms
        self._proc: Gio.Subprocess | None = None
        self._stream: Gio.DataInputStream | None = None
        self._cancellable: Gio.Cancellable | None = None
        self._source: int | None = None
        self._event: str | None = None
        self._id: int | None = None
        self._nodes: set[int] = set()

    def start(self) -> bool:
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        try:
            self._proc = launcher.spawnv(["pw-mon", "-N", "-o", "-a"])
        except GLib.Error:
            return False
        self._stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._cancellable = Gio.Cancellable()
        self._read()
        return True

    def stop(self) -> None:
        if self._cancellable is not None:
            self._cancellable.cancel()
            self._cancellable = None
        if self._proc is not None:
            self._proc.force_exit()
            self._proc = None
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None

    def feed(self, line: str) -> None:
        """Interpreta uma linha do pw-mon (separado da leitura para os testes)."""
        line = line.strip()
        if line in self._EVENTS:
            self._event, self._id = line, None
        elif line.startswith("id:"):
            try:
                self._id = int(line[3:])
            except ValueError:
                self._id = None
            if self._event == "removed:" and self._id in self._nodes:
                self._nodes.discard(self._id)
                self._kick()
        elif line.startswith("type: PipeWire:Interface:Node") and self._id is not None:
            if self._event in ("added:", "changed:"):
                self._nodes.add(self._id)
                self._kick()

    def _read(self) -> None:
        self._stream.read_line_async(GLib.PRIORITY_LOW, self._cancellable, self._on_line)

    def _on_line(self, stream, result) -> None:
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            return  # cancelado (stop) ou erro de leitura
        if line is None:  # pw-mon terminou
            self.stop()
            self._on_exit()
            return
        self.feed(line)
        self._read()

    def _kick(self) -> None:
        if self._source is not None:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(self._debounce_ms, self._fire)

    def _fire(self) -> bool:
        self._source = None
        self._on_change()
        return GLib.SOURCE_REMOVE
