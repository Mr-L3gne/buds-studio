"""Perfil de áudio Bluetooth (A2DP ↔ HFP/HSP) e codec, via PipeWire.

Extra do Buds Studio (o app original não tem). A troca automática para HFP acontece quando
algum programa grava áudio (um stream `Stream/Input/Audio`) e volta para A2DP quando ninguém
mais grava.
"""

from __future__ import annotations

from dataclasses import dataclass

from gi.repository import GLib, GObject

from ..transport import bluez
from . import pipewire as pw

_POLL_S = 3
_RELEASE_POLLS = 2  # polls seguidos sem gravação antes de voltar ao A2DP


@dataclass(frozen=True)
class AudioProfile:
    index: int
    name: str
    description: str
    available: bool

    @property
    def kind(self) -> str:
        if self.name.startswith("a2dp"):
            return "a2dp"
        if self.name.startswith("headset") or "hsp" in self.name or "hfp" in self.name:
            return "hfp"
        return "off" if self.name == "off" else "other"


@dataclass(frozen=True)
class CardInfo:
    device_id: int
    profiles: tuple[AudioProfile, ...]
    current: AudioProfile | None
    codec: str | None
    sink_node: str | None = None  # node.name da saída do fone (alvo do EQ de sistema)


def parse_card(objects: list, address: str) -> CardInfo | None:
    address = address.upper()
    card = None
    for obj in objects:
        props = pw.props_of(obj)
        if obj.get("type") == "PipeWire:Interface:Device" and str(props.get("api.bluez5.address", "")).upper() == address:
            card = obj
            break
    if card is None:
        return None
    params = pw.params_of(card)
    profiles = tuple(
        AudioProfile(
            index=int(p.get("index", -1)),
            name=str(p.get("name", "")),
            description=str(p.get("description", "")),
            available=p.get("available", "yes") != "no",
        )
        for p in params.get("EnumProfile", [])
        if isinstance(p, dict)
    )
    current_index = next((int(p.get("index", -1)) for p in params.get("Profile", []) if isinstance(p, dict)), None)
    current = next((p for p in profiles if p.index == current_index), None)
    codec = None
    sink_node = None
    for obj in objects:
        props = pw.props_of(obj)
        if obj.get("type") == "PipeWire:Interface:Node" and props.get("device.id") == card["id"]:
            codec = props.get("api.bluez5.codec") or codec
            if str(props.get("media.class", "")).startswith("Audio/Sink"):
                sink_node = props.get("node.name")
                break
    return CardInfo(card["id"], profiles, current, codec, sink_node)


def recording_streams(objects: list) -> list[str]:
    """Programas gravando áudio agora (exclui monitores de saída e o próprio app)."""
    names = []
    for obj in objects:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = pw.props_of(obj)
        if props.get("media.class") != "Stream/Input/Audio":
            continue
        if str(props.get("stream.capture.sink", "")).lower() == "true":
            continue
        if str(props.get("node.name", "")).startswith("buds_studio"):
            continue
        state = (obj.get("info") or {}).get("state")
        if state not in (None, "running", "idle"):
            continue
        names.append(props.get("application.name") or props.get("node.name") or "?")
    return names


def pick_profile(card: CardInfo, kind: str) -> AudioProfile | None:
    candidates = [p for p in card.profiles if p.kind == kind and p.available]
    if not candidates:
        return None
    if kind == "hfp":
        # Prefere mSBC (banda larga) se existir.
        for p in candidates:
            if "msbc" in p.name:
                return p
        return candidates[0]
    # A2DP: o perfil genérico "a2dp-sink" deixa o PipeWire escolher o melhor codec.
    for p in candidates:
        if p.name == "a2dp-sink":
            return p
    return candidates[0]


class AudioService(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self.address: str | None = None
        self.card: CardInfo | None = None
        self.available = pw.tool_available("pw-dump") and pw.tool_available("pw-cli")
        self.autoswitch = False
        self.auto_switched_from: AudioProfile | None = None
        self.recorders: list[str] = []
        self._idle_polls = 0
        self._poll_source: int | None = None

    def set_address(self, address: str | None) -> None:
        self.address = address
        self.card = None
        self.refresh()
        self._update_polling()

    def set_autoswitch(self, enabled: bool) -> None:
        self.autoswitch = enabled
        self._update_polling()

    def refresh(self, on_done=None) -> None:
        if not (self.available and self.address):
            if on_done:
                on_done()
            return

        def got(objects, error):
            if objects is not None:
                self.card = parse_card(objects, self.address)
                self.recorders = recording_streams(objects)
            self.emit("changed")
            if on_done:
                on_done()

        pw.dump(got)

    def set_kind(self, kind: str, on_done=None) -> None:
        card = self.card
        if card is None:
            self.emit("error", "card")
            return
        profile = pick_profile(card, kind)
        if profile is None:
            self.emit("error", kind)
            return
        self.set_profile(profile.index, on_done)

    def set_profile(self, index: int, on_done=None) -> None:
        card = self.card
        if card is None:
            return

        def finished(ok, _out, err):
            if not ok:
                self.emit("error", err.strip() or "pw-cli")
            GLib.timeout_add(600, lambda: (self.refresh(on_done), GLib.SOURCE_REMOVE)[1])

        pw.run(["pw-cli", "set-param", str(card.device_id), "Profile", f"{{ index: {index}, save: true }}"], finished)

    def is_default_output(self, on_done) -> None:
        """on_done(bool): a saída do fone é a saída padrão do sistema?"""
        card = self.card
        if card is None or not card.sink_node:
            on_done(False)
            return

        def got(_ok, out, _err):
            on_done(any(card.sink_node in line for line in out.splitlines() if "default.configured.audio.sink" in line))

        pw.run(["pw-metadata", "0", "default.configured.audio.sink"], got, manager=False)

    def use_as_output(self, device_path: str, on_done) -> None:
        """Torna o fone a saída de áudio padrão. Se o áudio Bluetooth (A2DP) não estiver
        conectado, conecta pelo BlueZ antes. on_done(erro ou None)."""

        def set_default() -> None:
            card = self.card
            if card is None or not card.sink_node:
                on_done("sink")
                return
            pw.run(
                ["pw-metadata", "0", "default.configured.audio.sink", f'{{"name":"{card.sink_node}"}}', "Spa:String:JSON"],
                lambda ok, _o, err: on_done(None if ok else (err.strip() or "pw-metadata")),
            )

        if self.card is not None and self.card.sink_node:
            set_default()
            return

        attempts = [0]

        def poll() -> bool:
            attempts[0] += 1

            def after():
                if self.card is not None and self.card.sink_node:
                    set_default()
                elif attempts[0] < 10:
                    GLib.timeout_add(1000, poll)
                else:
                    on_done("sink")

            self.refresh(after)
            return GLib.SOURCE_REMOVE

        def connected(error) -> None:
            if error:
                on_done(error)
            else:
                GLib.timeout_add(1000, poll)

        try:
            bluez.connect_device(bluez.system_bus(), device_path, connected)
        except bluez.BluezError as exc:
            on_done(str(exc))

    def _update_polling(self) -> None:
        want = self.available and self.autoswitch and self.address is not None
        if want and self._poll_source is None:
            self._poll_source = GLib.timeout_add_seconds(_POLL_S, self._poll)
        elif not want and self._poll_source is not None:
            GLib.source_remove(self._poll_source)
            self._poll_source = None

    def _poll(self) -> bool:
        self.refresh(self._apply_autoswitch)
        return GLib.SOURCE_CONTINUE

    def _apply_autoswitch(self) -> None:
        card = self.card
        if card is None or card.current is None:
            return
        if self.recorders:
            self._idle_polls = 0
            if card.current.kind == "a2dp":
                self.auto_switched_from = card.current
                self.set_kind("hfp")
        elif self.auto_switched_from is not None and card.current.kind == "hfp":
            self._idle_polls += 1
            if self._idle_polls >= _RELEASE_POLLS:
                target = self.auto_switched_from
                self.auto_switched_from = None
                self._idle_polls = 0
                self.set_profile(target.index)

    def shutdown(self) -> None:
        self.autoswitch = False
        self._update_polling()
