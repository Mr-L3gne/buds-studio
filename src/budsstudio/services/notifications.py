"""Notificações (portal no Flatpak): fone conectado/desconectado e bateria baixa."""

from __future__ import annotations

from gi.repository import Gio

from .. import APP_ID
from ..i18n import _
from ..transport.connection import ConnectionState

_HYSTERESIS = 5


class NotificationService:
    def __init__(self, app: Gio.Application, device, config) -> None:
        self.app = app
        self.device = device
        self.config = config
        self._was_connected = False
        self._low: dict[str, bool] = {}
        device.connect("connection-changed", self._on_connection)
        device.connect("state-changed", self._on_state)

    def _key(self, key: str) -> str:
        address = self.device.device.address if self.device.device else ""
        return f"{key}-{address}"

    def _send(self, key: str, title: str, body: str, priority=Gio.NotificationPriority.NORMAL) -> None:
        key = self._key(key)
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon.new(APP_ID))
        notification.set_priority(priority)
        notification.set_default_action("app.show")
        self.app.send_notification(key, notification)

    def _on_connection(self, _device, state: str, _detail: str) -> None:
        connected = state == ConnectionState.CONNECTED.value
        name = self.device.device.name if self.device.device else ""
        if self.config.notify_connection:
            if connected and not self._was_connected:
                self._send("connection", _("Earbuds connected"), name)
            elif self._was_connected and not connected:
                self._send("connection", _("Earbuds disconnected"), name)
        if connected:
            self._low.clear()
        self._was_connected = connected

    def _on_state(self, _device) -> None:
        if not self.config.notify_battery:
            return
        s = self.device.state
        threshold = self.config.battery_low_threshold
        sides = (
            ("left", _("Left earbud"), s.battery_left, s.charging_left),
            ("right", _("Right earbud"), s.battery_right, s.charging_right),
        )
        for key, label, level, charging in sides:
            if level is None or level <= 0:
                continue
            if level <= threshold and not charging:
                if not self._low.get(key):
                    self._low[key] = True
                    self._send(
                        f"battery-{key}",
                        _("Low battery"),
                        _("{device} — {side}: {level}%").format(
                            device=self.device.device.name if self.device.device else "", side=label, level=level),
                        Gio.NotificationPriority.HIGH,
                    )
            elif level > threshold + _HYSTERESIS or charging:
                if self._low.pop(key, None):
                    self.app.withdraw_notification(self._key(f"battery-{key}"))
