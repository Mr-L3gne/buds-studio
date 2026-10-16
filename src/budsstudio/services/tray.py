"""Ícone na bandeja (StatusNotifierItem + com.canonical.dbusmenu) direto em D-Bus.

Se não houver `org.kde.StatusNotifierWatcher` (ex.: GNOME sem a extensão AppIndicator), o
ícone simplesmente não aparece e o app segue normal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from gi.repository import Gio, GLib

from .. import APP_ID, APP_NAME

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"

_ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>
"""

_MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})"/><arg type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
  </interface>
</node>
"""


@dataclass
class MenuItem:
    label: str = ""
    action: Callable[[], None] | None = None
    enabled: bool = True
    separator: bool = False
    radio: bool | None = None  # None = item comum; True/False = estado do botão de opção
    children: list["MenuItem"] = field(default_factory=list)


class TrayIcon:
    def __init__(self, on_activate: Callable[[], None]) -> None:
        self._on_activate = on_activate
        self._bus: Gio.DBusConnection | None = None
        self._ids: list[int] = []
        self._watch_id: int | None = None
        self._revision = 1
        self._items: dict[int, MenuItem] = {}
        self._root = MenuItem()
        self.title = APP_NAME
        self.tooltip = ""
        self.registered = False

    def start(self) -> None:
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return
        item_info = Gio.DBusNodeInfo.new_for_xml(_ITEM_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]
        self._ids.append(
            self._bus.register_object(ITEM_PATH, item_info, self._item_call, self._item_get, None)
        )
        self._ids.append(
            self._bus.register_object(MENU_PATH, menu_info, self._menu_call, self._menu_get, None)
        )
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._bus, WATCHER, Gio.BusNameWatcherFlags.NONE, self._on_watcher, self._on_watcher_lost
        )

    def stop(self) -> None:
        if self._bus is None:
            return
        if self._watch_id is not None:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = None
        for reg in self._ids:
            self._bus.unregister_object(reg)
        self._ids.clear()
        self.registered = False

    def _on_watcher(self, _conn, _name, _owner) -> None:
        self._bus.call(
            WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._bus.get_unique_name(),)), None,
            Gio.DBusCallFlags.NONE, 3000, None, self._registered_cb,
        )

    def _registered_cb(self, bus, result) -> None:
        try:
            bus.call_finish(result)
            self.registered = True
        except GLib.Error:
            self.registered = False

    def _on_watcher_lost(self, *_args) -> None:
        self.registered = False

    # Atualizações vindas do app

    def update(self, title: str, tooltip: str, menu: list[MenuItem]) -> None:
        self.title, self.tooltip = title, tooltip
        self._root = MenuItem(children=menu)
        self._items = {}
        self._index(self._root, [0])
        self._revision += 1
        if self._bus is None:
            return
        for signal in ("NewTitle", "NewToolTip"):
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", signal, None)
        self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (self._revision, 0)))

    def _emit(self, path: str, iface: str, name: str, params) -> None:
        try:
            self._bus.emit_signal(None, path, iface, name, params)
        except GLib.Error:
            pass

    def _index(self, item: MenuItem, counter: list[int]) -> None:
        item_id = counter[0]
        self._items[item_id] = item
        item._id = item_id  # type: ignore[attr-defined]
        for child in item.children:
            counter[0] += 1
            self._index(child, counter)

    # StatusNotifierItem

    def _item_get(self, _conn, _sender, _path, _iface, prop):
        values = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", APP_ID),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", APP_ID),
            "IconThemePath": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (APP_ID, [], self.title, self.tooltip)),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(prop)

    def _item_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(lambda: (self._on_activate(), GLib.SOURCE_REMOVE)[1])
        invocation.return_value(None)

    # dbusmenu

    def _menu_get(self, _conn, _sender, _path, _iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    def _props(self, item: MenuItem) -> dict:
        if item is self._root:
            return {"children-display": GLib.Variant("s", "submenu")}
        if item.separator:
            return {"type": GLib.Variant("s", "separator")}
        props = {
            "label": GLib.Variant("s", item.label.replace("_", "__")),
            "enabled": GLib.Variant("b", item.enabled),
            "visible": GLib.Variant("b", True),
        }
        if item.radio is not None:
            props["toggle-type"] = GLib.Variant("s", "radio")
            props["toggle-state"] = GLib.Variant("i", 1 if item.radio else 0)
        if item.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        return props

    def _layout(self, item: MenuItem, depth: int) -> GLib.Variant:
        children = []
        if depth != 0:
            children = [
                GLib.Variant("v", self._layout(child, depth - 1)) for child in item.children
            ]
        return GLib.Variant("(ia{sv}av)", (item._id, self._props(item), children))  # type: ignore[attr-defined]

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            parent, depth, _names = params.unpack()
            item = self._items.get(parent, self._root)
            layout = self._layout(item, depth)
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self._revision), layout))
        elif method == "GetGroupProperties":
            ids, _names = params.unpack()
            ids = ids or list(self._items)
            result = [(i, self._props(self._items[i])) for i in ids if i in self._items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            value = self._props(self._items.get(item_id, self._root)).get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event, _data, _ts = params.unpack()
            self._fire(item_id, event)
            invocation.return_value(None)
        elif method == "EventGroup":
            events = params.unpack()[0]
            for item_id, event, _data, _ts in events:
                self._fire(item_id, event)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _fire(self, item_id: int, event: str) -> None:
        item = self._items.get(item_id)
        if event == "clicked" and item is not None and item.action is not None and item.enabled:
            action = item.action
            GLib.idle_add(lambda: (action(), GLib.SOURCE_REMOVE)[1])
