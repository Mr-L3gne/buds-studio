"""EQ de sistema (extra, desligado por padrão): EQ paramétrico de 10 bandas em software, somado
ao EQ do fone.

Roda um processo `pipewire -c <conf>` com o `module-filter-chain` (filtros `bq_peaking`
internos do PipeWire). Ele cria a saída virtual "Buds Studio EQ", ligada à saída do fone, e
o app a torna a saída padrão enquanto o EQ estiver ligado. Os ganhos mudam ao vivo com
`pw-cli set-param … Props`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from gi.repository import Gio, GLib, GObject

from . import pipewire as pw
from .config import SYSTEM_EQ_BANDS_HZ, SYSTEM_EQ_GAIN_LIMIT

SINK_NAME = "buds_studio_eq"
_Q = 1.41
_FIND_NODE_DELAY_MS = 800
_GAIN_DEBOUNCE_MS = 150


def pipewire_binary() -> str | None:
    env = os.environ.get("BUDS_STUDIO_PIPEWIRE")
    if env:
        return env
    for candidate in ("/app/bin/pipewire",):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("pipewire")


def build_config(gains: list[float], target: str, description: str) -> str:
    nodes = []
    links = []
    for i, (freq, gain) in enumerate(zip(SYSTEM_EQ_BANDS_HZ, gains), start=1):
        nodes.append(
            f'            {{ type = builtin name = band{i} label = bq_peaking '
            f'control = {{ "Freq" = {float(freq)} "Q" = {_Q} "Gain" = {float(gain):.2f} }} }}'
        )
        if i > 1:
            links.append(f'            {{ output = "band{i - 1}:Out" input = "band{i}:In" }}')
    return f"""# Gerado pelo Buds Studio (EQ de sistema).
context.properties = {{
    log.level = 0
    media.category = Manager
}}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ nice.level = -11 }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "{description}"
            media.name       = "{description}"
            filter.graph = {{
                nodes = [
{chr(10).join(nodes)}
                ]
                links = [
{chr(10).join(links)}
                ]
            }}
            audio.channels = 2
            audio.position = [ FL FR ]
            capture.props = {{
                node.name   = "{SINK_NAME}"
                media.class = Audio/Sink
            }}
            playback.props = {{
                node.name     = "{SINK_NAME}.output"
                node.passive  = true
                target.object = "{target}"
            }}
        }}
    }}
]
"""


class SystemEqService(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, description: str = "Buds Studio EQ") -> None:
        super().__init__()
        self.description = description
        self.gains = [0.0] * len(SYSTEM_EQ_BANDS_HZ)
        self.enabled = False
        self.target_sink: str | None = None
        self.node_id: int | None = None
        self._proc: Gio.Subprocess | None = None
        self._previous_default: str | None = None
        self._gain_source: int | None = None

    @property
    def available(self) -> bool:
        return pipewire_binary() is not None and pw.tool_available("pw-cli")

    @property
    def running(self) -> bool:
        return self._proc is not None

    def set_target_sink(self, node_name: str | None) -> None:
        """Saída do fone (ex.: bluez_output.XX_XX….1). Reinicia o EQ se ela mudar."""
        if node_name == self.target_sink:
            return
        self.target_sink = node_name
        if self.enabled:
            self._stop()
            if node_name:
                self._start()

    def set_gains(self, gains: list[float]) -> None:
        gains = [max(-SYSTEM_EQ_GAIN_LIMIT, min(SYSTEM_EQ_GAIN_LIMIT, float(g))) for g in gains]
        if gains == self.gains:
            return  # sem mudança: nem pw-cli nem "changed"
        self.gains = gains
        if self.running and self.node_id is not None:
            if self._gain_source is not None:
                GLib.source_remove(self._gain_source)
            self._gain_source = GLib.timeout_add(_GAIN_DEBOUNCE_MS, self._push_gains)
        self.emit("changed")

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self.enabled and (self.running or not enabled or not self.target_sink):
            return  # sem mudança
        self.enabled = enabled
        if enabled and not self.running and self.target_sink:
            self._start()
        elif not enabled and self.running:
            self._stop()
        self.emit("changed")

    def _start(self) -> None:
        binary = pipewire_binary()
        if binary is None:
            self.emit("error", "pipewire")
            return
        conf = pw.runtime_dir() / "system-eq.conf"
        conf.write_text(build_config(self.gains, self.target_sink or "", self.description))
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
        try:
            self._proc = launcher.spawnv([binary, "-c", str(conf)])
        except GLib.Error as exc:
            self._proc = None
            self.emit("error", exc.message)
            return
        self._proc.wait_async(None, self._on_exit)
        GLib.timeout_add(_FIND_NODE_DELAY_MS, self._find_node)

    def _on_exit(self, proc, result) -> None:
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        if proc is self._proc:
            self._proc = None
            self.node_id = None
            if self.enabled:
                self.emit("error", "exit")
            self.emit("changed")

    def _find_node(self) -> bool:
        def got(objects, _error):
            if not objects:
                return
            for obj in objects:
                props = pw.props_of(obj)
                if obj.get("type") == "PipeWire:Interface:Node" and props.get("node.name") == SINK_NAME:
                    self.node_id = obj["id"]
                    break
            self._make_default()
            self.emit("changed")

        pw.dump(got)
        return GLib.SOURCE_REMOVE

    def _make_default(self) -> None:
        def current(ok, out, _err):
            # Linha: update: id:0 key:'default.configured.audio.sink' value:'{"name":"…"}' type:'Spa:String:JSON'
            for line in out.splitlines():
                if "default.configured.audio.sink" in line and "value:'" in line:
                    value = line.split("value:'", 1)[1].split("'", 1)[0]
                    if SINK_NAME not in value:
                        self._previous_default = value
            pw.run(["pw-metadata", "0", "default.configured.audio.sink", f'{{"name":"{SINK_NAME}"}}', "Spa:String:JSON"])

        pw.run(["pw-metadata", "0", "default.configured.audio.sink"], current)

    def _restore_default(self, wait: bool = False) -> None:
        if self._previous_default:
            argv = ["pw-metadata", "0", "default.configured.audio.sink", self._previous_default, "Spa:String:JSON"]
        else:
            argv = ["pw-metadata", "-d", "0", "default.configured.audio.sink"]
        self._previous_default = None
        if not wait:
            pw.run(argv)
            return
        # Ao fechar o app o main loop já parou: espera o comando terminar.
        env = dict(os.environ, PIPEWIRE_CONFIG_DIR=str(pw.client_config_dir()))
        try:
            subprocess.run(argv, env=env, timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass

    def _push_gains(self) -> bool:
        self._gain_source = None
        if self.node_id is None:
            return GLib.SOURCE_REMOVE
        params = " ".join(f'"band{i}:Gain" {g:.2f}' for i, g in enumerate(self.gains, start=1))
        pw.run(["pw-cli", "set-param", str(self.node_id), "Props", f"{{ params = [ {params} ] }}"])
        return GLib.SOURCE_REMOVE

    def _stop(self, wait: bool = False) -> None:
        proc, self._proc = self._proc, None
        self.node_id = None
        self._restore_default(wait)
        if proc is not None:
            proc.send_signal(15)

    def shutdown(self) -> None:
        if self.running:
            self._stop(wait=True)
