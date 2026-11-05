"""Executa um comando da CLI de forma assíncrona, dentro do main loop do app."""

from __future__ import annotations

from typing import Callable

from gi.repository import GLib

from ..i18n import _
from ..protocol import Cap, MsgId, NoiseCycle
from ..protocol.messages import NOISE_KEYS, PRESET_KEYS, TouchHoldOption
from ..services.device import CommandError, format_packet
from ..services.profiles import apply_profile
from ..services.eq_curves import preset_gains
from ..transport.bluez import BluezError
from ..ui.labels import fit_label, noise_labels, preset_labels, system_eq_preset_labels, touch_hold_labels
from . import CliError, dumps, parse_on_off

# Quanto esperar o ack 0x42 depois de um comando.
_ACK_WAIT_MS = 3000
# Depois do primeiro 0x61, quanto esperar pelas mensagens de versão/serial (--info).
_INFO_WAIT_MS = 2500
_FIT_WAIT_S = 25


class CliRunner:
    def __init__(self, app, args, out: Callable[[str], None], err: Callable[[str], None],
                 finish: Callable[[int], None]) -> None:
        self.app = app
        self.device = app.device
        self.args = args
        self.out = out
        self.err = err
        self._finish = finish
        self._handlers: list[int] = []
        self._sources: list[int] = []
        self._done = False
        self._expect_ack: int | None = None

    # Ciclo de vida

    def start(self) -> None:
        a = self.args
        if a.debug:
            self._on(self.device, "packet", lambda _d, p: self.err(format_packet(p)))
        try:
            if a.list:
                return self._list()
            if a.profiles:
                return self._profiles()
            if a.system_eq:
                return self._system_eq()
            if a.system_eq_preset:
                return self._system_eq_preset()
            self._ensure_connected(self._run_action)
        except (CliError, BluezError, CommandError) as exc:
            self.fail(str(exc))

    def finish(self, code: int = 0) -> None:
        if self._done:
            return
        self._done = True
        for obj, handler in self._handlers:
            obj.disconnect(handler)
        for source in self._sources:
            GLib.source_remove(source)
        self._finish(code)

    def fail(self, message: str, code: int = 1) -> None:
        if message:
            self.err(_("error: {message}").format(message=message))
        self.finish(code)

    def _on(self, obj, signal, callback) -> None:
        self._handlers.append((obj, obj.connect(signal, callback)))

    def _after(self, ms: int, callback) -> None:
        def fire():
            self._sources.remove(source)
            if not self._done:
                callback()
            return GLib.SOURCE_REMOVE

        source = GLib.timeout_add(ms, fire)
        self._sources.append(source)

    # Conexão

    def _ensure_connected(self, then) -> None:
        a = self.args
        device = self.device
        wanted = self.app.find_device(a.device) if a.device else None
        if a.device and wanted is None:
            raise CliError(_("No paired compatible earbuds named or with address {address}").format(address=a.device))
        same = device.device is not None and (wanted is None or wanted.path == device.device.path)
        if same and device.connected and device.state.ready and a.channel is None:
            then()
            return

        waiters: list[int] = []

        def stop_waiting() -> None:
            for handler in waiters:
                if device.handler_is_connected(handler):
                    device.disconnect(handler)
            self._handlers = [(o, h) for o, h in self._handlers if h not in waiters]

        def on_ready(*_args) -> None:
            stop_waiting()
            GLib.idle_add(lambda: (then(), GLib.SOURCE_REMOVE)[1])

        started = [False]

        def on_connection(_d, state, detail) -> None:
            # Trocar o fone selecionado reemite o estado atual ("disconnected"); só conta como
            # falha depois que a conexão começou de fato.
            if state in ("connecting", "connected"):
                started[0] = True
            elif state in ("waiting", "disconnected") and started[0] and not self._done:
                stop_waiting()
                self.fail(detail or _("Could not connect to the earbuds"))

        for signal, callback in (("ready", on_ready), ("connection-changed", on_connection)):
            handler = device.connect(signal, callback)
            waiters.append(handler)
            self._handlers.append((device, handler))
        self._after(int(a.timeout * 1000), lambda: self.fail(_("Timed out waiting for the earbuds")))
        if not (same and device.connection.value in ("connecting", "connected")) or a.channel is not None:
            self.app.connect_device_for_cli(wanted, a.channel)

    # Ações

    def _run_action(self) -> None:
        if self._done:
            return
        a = self.args
        try:
            if a.status:
                return self._status()
            if a.info:
                return self._after(_INFO_WAIT_MS, self._info)
            if a.preset:
                return self._command(MsgId.EQUALIZER, self.device.set_preset, PRESET_KEYS[a.preset],
                                     done=lambda s: _("Equalizer: {value}").format(value=preset_labels()[s.equalizer]))
            if a.anc:
                return self._command(MsgId.NOISE_CONTROLS, self.device.set_noise_control, NOISE_KEYS[a.anc],
                                     done=lambda s: _("Noise control: {value}").format(value=noise_labels()[s.noise_control]))
            if a.profile:
                return self._profile(a.profile)
            if a.set:
                return self._set(a.set)
            if a.find:
                return self._find(a.find)
            if a.mute:
                left = a.mute in ("left", "both")
                right = a.mute in ("right", "both")
                self.device.set_find_mute(left, right)
                self.out(_("Mute: left {left}, right {right}").format(left=_on(left), right=_on(right)))
                return self.finish(0)
            if a.fit_test:
                return self._fit_test()
            if a.audio_profile:
                return self._audio_profile(a.audio_profile)
        except (CliError, CommandError, ValueError) as exc:
            self.fail(str(exc))

    def _command(self, msg_id: int, call, *values, done=None) -> None:
        call(*values)

        def acked(_d, ack_id):
            if ack_id == msg_id:
                self.out(done(self.device.state) if done else _("Confirmed by the earbuds"))
                self.finish(0)

        self._on(self.device, "ack", acked)
        self._after(_ACK_WAIT_MS, lambda: (self.out(_("Sent (the earbuds sent no confirmation)")), self.finish(0)))

    def _sent_no_ack(self, text: str) -> None:
        # Comandos que o plugin original não confirma (sem case em g8.T.f).
        self.out(text)
        self._after(400, lambda: self.finish(0))

    def _status(self) -> None:
        s = self.device.state
        dev = self.device.device
        model = self.device.model
        data = {
            "device": dev.name if dev else None,
            "address": dev.address if dev else None,
            "model": model.name,
            "validated": model.validated,
            "battery": {"left": s.battery_left, "right": s.battery_right, "case": s.battery_case},
            "charging": {"left": s.charging_left, "right": s.charging_right, "case": s.charging_case},
            "wearing": {"left": s.wearing_left, "right": s.wearing_right},
            "equalizer": _key_for(PRESET_KEYS, s.equalizer),
            "noise_control": _key_for(NOISE_KEYS, s.noise_control),
            "balance": s.balance,
            "game_mode": s.game_mode,
            "anc_with_one_earbud": s.anc_with_one_earbud,
            "ambient_during_calls": s.ambient_during_calls,
            "in_ear_detection": s.in_ear_detection,
            "ambient_volume": None if s.ambient is None else [s.ambient.volume_left, s.ambient.volume_right],
            "extra_high_ambient": s.extra_high_ambient,
            "touch": None if s.touch is None else {n: getattr(s.touch, n) for n in s.touch.names()},
            "touch_and_hold": {"left": _hold_key(s.touch_hold_left), "right": _hold_key(s.touch_hold_right)},
            "noise_cycle": None if s.noise_cycle_first is None else _cycle_list(s.noise_cycle_first),
        }
        if self.args.json:
            self.out(dumps(data))
            return self.finish(0)

        def pct(v):
            return "—" if v is None else f"{v}%"

        def ear(worn, charging):
            parts = []
            if charging:
                parts.append(_("charging"))
            if worn is not None:
                parts.append(_("in ear") if worn else _("out of ear"))
            return f" ({', '.join(parts)})" if parts else ""

        lines = [
            f"{_('Earbuds')}: {data['device']} — {model.name or '?'}" + ("" if model.validated else f" [{_('experimental')}]"),
            f"{_('Battery')}: {_('L')} {pct(s.battery_left)}{ear(s.wearing_left, s.charging_left)} · "
            f"{_('R')} {pct(s.battery_right)}{ear(s.wearing_right, s.charging_right)} · "
            f"{_('case')} {pct(s.battery_case)}{ear(None, s.charging_case)}",
        ]
        if s.equalizer is not None:
            lines.append(f"{_('Equalizer')}: {preset_labels().get(s.equalizer, s.equalizer)}")
        if s.noise_control is not None:
            lines.append(f"{_('Noise control')}: {noise_labels().get(s.noise_control, s.noise_control)}")
        if s.balance is not None:
            lines.append(f"{_('Balance')}: {s.balance} (0 = {_('left')}, 32 = {_('right')})")
        for label, value in (
            (_("Gaming mode"), s.game_mode),
            (_("Noise control with one earbud"), s.anc_with_one_earbud),
            (_("Ambient sound during calls"), s.ambient_during_calls),
            (_("In-ear detection for calls"), s.in_ear_detection),
            (_("Extra-high ambient volume"), s.extra_high_ambient),
        ):
            if value is not None:
                lines.append(f"{label}: {_on(value)}")
        if s.ambient is not None:
            lines.append(f"{_('Ambient volume')}: {_('L')} {s.ambient.volume_left} · {_('R')} {s.ambient.volume_right}")
        if s.touch is not None:
            on = [n for n in s.touch.names() if getattr(s.touch, n)]
            lines.append(f"{_('Touch')}: {', '.join(on) or '—'}")
        if s.touch_hold_left is not None:
            labels = touch_hold_labels()
            lines.append(f"{_('Touch and hold')}: {_('L')} {labels.get(s.touch_hold_left, s.touch_hold_left)} · "
                         f"{_('R')} {labels.get(s.touch_hold_right, s.touch_hold_right)}")
        if s.noise_cycle_first is not None:
            lines.append(f"{_('Noise control cycle')}: {', '.join(_cycle_list(s.noise_cycle_first))}")
        self.out("\n".join(lines))
        self.finish(0)

    def _info(self) -> None:
        info, dev, model = self.device.info, self.device.device, self.device.model
        data = {
            "model": model.name,
            "plugin": model.plugin,
            "validated": model.validated,
            "name": dev.name if dev else None,
            "address": dev.address if dev else None,
            "firmware": {"left": info.firmware_left, "right": info.firmware_right},
            "serial": {"left": info.serial_left, "right": info.serial_right},
            "case": {"firmware": info.case_firmware, "serial": info.case_serial},
            "hardware": {"left": info.hw_left, "right": info.hw_right},
            "touch_firmware": {"left": info.touch_fw_left, "right": info.touch_fw_right},
        }
        if self.args.json:
            self.out(dumps(data))
        else:
            def v(x):
                return x if x not in (None, "") else "—"

            self.out("\n".join([
                f"{_('Model')}: {v(model.name)}" + ("" if model.validated else f" [{_('experimental')}]"),
                f"{_('Name')}: {v(data['name'])}",
                f"{_('Bluetooth address')}: {v(data['address'])}",
                f"{_('Firmware')}: {_('L')} {v(info.firmware_left)} · {_('R')} {v(info.firmware_right)}",
                f"{_('Serial number')}: {_('L')} {v(info.serial_left)} · {_('R')} {v(info.serial_right)}",
                f"{_('Case')}: {_('firmware')} {v(info.case_firmware)} · {_('serial')} {v(info.case_serial)}",
            ]))
        self.finish(0)

    def _list(self) -> None:
        devices = self.app.list_devices()
        if self.args.json:
            self.out(dumps([{"name": d.name, "remote_name": d.remote_name, "address": d.address,
                             "connected": d.connected,
                             "added": d.address.upper() in {a.upper() for a in self.app.config.devices},
                             "selected": d.address.upper() == self.app.manager.selected_address}
                            for d in devices]))
        elif not devices:
            self.out(_("No paired compatible earbuds."))
        else:
            added = {a.upper() for a in self.app.config.devices}
            for d in devices:
                service = self.app.manager.get(d.address)
                status = _("connected") if (service.connected if service else d.connected) else _("disconnected")
                in_app = _("in Buds Studio") if (service is not None or d.address.upper() in added) else _("not added")
                mark = "*" if service is not None and d.address.upper() == self.app.manager.selected_address else " "
                self.out(f"{mark} {d.address}  {d.name}  ({status}, {in_app})")
        self.finish(0)

    def _profiles(self) -> None:
        names = [p.name for p in self.app.profiles.profiles]
        self.out("\n".join(names) if names else _("No saved profiles yet"))
        self.finish(0)

    def _profile(self, name: str) -> None:
        profile = self.app.profiles.get(name)
        if profile is None:
            raise CliError(_("Profile “{name}” not found").format(name=name))
        skipped = apply_profile(profile, self.device, self.app.system_eq if self.app.persistent else None)
        text = _("Profile “{name}” applied").format(name=profile.name)
        if skipped:
            text += " — " + _("not applied: {items}").format(items=", ".join(skipped))
        self._sent_no_ack(text)

    def _set(self, expr: str) -> None:
        if "=" not in expr:
            raise CliError(_("Use --set KEY=VALUE"))
        key, value = (part.strip() for part in expr.split("=", 1))
        d = self.device
        if key == "balance":
            number = int(value)
            return self._command(MsgId.SOUND_BALANCE, d.set_balance, number,
                                 done=lambda s: _("Balance: {value}").format(value=s.balance))
        acked = {
            "anc-one-earbud": (MsgId.ANC_WITH_ONE_EARBUD, d.set_anc_with_one_earbud),
            "ambient-during-calls": (MsgId.AMBIENT_DURING_CALLS, d.set_ambient_during_calls),
            "in-ear-detection": (MsgId.IN_EAR_DETECTION, d.set_in_ear_detection),
            "game-mode": (MsgId.GAME_MODE, d.set_game_mode),
        }
        if key in acked:
            msg_id, call = acked[key]
            enabled = parse_on_off(value)
            return self._command(msg_id, call, enabled,
                                 done=lambda _s: _("{key}: {value}").format(key=key, value=_on(enabled)))
        if key == "extra-high-ambient":
            enabled = parse_on_off(value)
            d.set_extra_high_ambient(enabled)
            return self._sent_no_ack(_("{key} sent: {value}").format(key=key, value=_on(enabled)))
        if key == "ambient-volume":
            left, right = (int(x) for x in value.split(","))
            d.set_ambient_volume(left, right)
            return self._sent_no_ack(_("Ambient volume sent: L {left} · R {right}").format(left=left, right=right))
        if key == "touch-controls":
            return self._command(MsgId.LOCK_TOUCHPAD, d.set_touch_field, "touch_controls", parse_on_off(value))
        if key.startswith("gesture."):
            name = key.split(".", 1)[1].replace("-", "_")
            if name not in ("tap", "double_tap", "triple_tap", "touch_and_hold", "calls_double_tap", "calls_touch_and_hold"):
                raise CliError(_("Unknown gesture: {name}").format(name=name))
            return self._command(MsgId.LOCK_TOUCHPAD, d.set_touch_field, name, parse_on_off(value))
        if key in ("hold-left", "hold-right"):
            options = {"noise": TouchHoldOption.NOISE_CONTROLS, "volume": TouchHoldOption.VOLUME}
            if value not in options:
                raise CliError(_("Use noise or volume"))
            chosen = options[value]
            s = d.state
            left, right = s.touch_hold_left, s.touch_hold_right
            if left is None:
                raise CliError(_("Touch settings not received yet"))
            if chosen == TouchHoldOption.VOLUME or TouchHoldOption.VOLUME in (left, right):
                left = right = chosen  # volume vale para os dois lados
            elif key == "hold-left":
                left = chosen
            else:
                right = chosen
            return self._command(MsgId.TOUCH_AND_HOLD_OPTION, d.set_touch_hold_options, left, right)
        if key == "noise-cycle":
            modes = {m.strip() for m in value.split(",") if m.strip()}
            unknown = modes - {"anc", "ambient", "off"}
            if unknown:
                raise CliError(_("Unknown modes: {modes}").format(modes=", ".join(sorted(unknown))))
            cycle = NoiseCycle("anc" in modes, "ambient" in modes, "off" in modes)
            return self._command(MsgId.NOISE_CYCLE, d.set_noise_cycle, cycle, cycle)
        raise CliError(_("Unknown key: {key}").format(key=key))

    def _find(self, what: str) -> None:
        if what == "start":
            s = self.device.state
            if (s.wearing_left or s.wearing_right) and not self.args.json:
                self.err(_("warning: the earbuds seem to be in someone's ears"))
            self.device.find_start()
            self.out(_("Ringing. Stop with: buds-studio --find stop"))
        else:
            self.device.find_stop()
            self.out(_("Stopped"))
        self._after(400, lambda: self.finish(0))

    def _fit_test(self) -> None:
        if not self.device.has(Cap.FIT_TEST):
            raise CliError(_("This model does not support this feature"))

        def result(_d, left, right):
            self.out(_("Left: {left} · Right: {right}").format(left=fit_label(left), right=fit_label(right)))
            self._after(400, lambda: self.finish(0))

        self._on(self.device, "fit-result", result)
        self.device.fit_test_start()
        self.out(_("Testing… keep still"))
        self._after(_FIT_WAIT_S * 1000, lambda: (self.device.fit_test_cancel(), self.fail(_("No result from the earbuds"))))

    def _audio_profile(self, kind: str) -> None:
        audio = self.app.audio
        if not audio.available:
            raise CliError(_("PipeWire tools are not available"))

        def after_set():
            card = audio.card
            if card is None or card.current is None:
                return self.fail(_("The earbuds audio device was not found in PipeWire"))
            self.out(_("Audio mode: {profile} · codec {codec}").format(
                profile=card.current.description, codec=(card.codec or "—").upper()))
            self.finish(0 if card.current.kind == kind else 1)

        def refreshed():
            if audio.card is None:
                return self.fail(_("The earbuds audio device was not found in PipeWire"))
            if audio.card.current and audio.card.current.kind == kind:
                return after_set()
            self._on(audio, "error", lambda _a, msg: self.fail(msg))
            audio.set_kind(kind, after_set)

        audio.set_address(self.device.device.address)
        audio.refresh(refreshed)

    def _system_eq(self) -> None:
        if not self.app.persistent:
            raise CliError(_("The system equalizer only runs while Buds Studio is open (window or tray). "
                             "Open it first, e.g. with: buds-studio --background"))
        enabled = self.args.system_eq == "on"
        self.app.config.system_eq_enabled = enabled
        self.app.save_config()
        self.app.update_system_eq()
        self.out(_("System equalizer: {state}").format(state=_on(enabled)))
        self.finish(0)

    def _system_eq_preset(self) -> None:
        if not self.app.persistent:
            raise CliError(_("The system equalizer only runs while Buds Studio is open (window or tray). "
                             "Open it first, e.g. with: buds-studio --background"))
        name = self.args.system_eq_preset
        gains = preset_gains(name)
        if gains is None:
            raise CliError(_("Unknown curve: {name}").format(name=name))
        self.app.config.system_eq_gains = gains
        self.app.save_config()
        self.app.update_system_eq()
        self.out(_("System equalizer curve: {name}").format(name=system_eq_preset_labels()[name]))
        self.finish(0)


def _on(value: bool) -> str:
    return _("on") if value else _("off")


def _key_for(table: dict, value):
    for key, item in table.items():
        if item == value:
            return key
    return value


def _hold_key(value):
    return {TouchHoldOption.NOISE_CONTROLS: "noise", TouchHoldOption.VOLUME: "volume"}.get(value, value)


def _cycle_list(cycle: NoiseCycle) -> list[str]:
    return [name for name in ("anc", "ambient", "off") if getattr(cycle, name)]
