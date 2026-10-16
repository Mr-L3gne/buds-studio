"""Janela principal: navegação no estilo do app original, barra lateral e seletor de aparelhos."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from ..i18n import _
from .builder import Ui
from .pages import PAGES, battery_summary
from .style import apply_background


class DeviceList:
    """Lista de aparelhos (nome, bateria e status). Usada na barra lateral e no seletor do topo."""

    def __init__(self, app, listbox: Gtk.ListBox, on_chosen) -> None:
        self.app = app
        self.listbox = listbox
        self.on_chosen = on_chosen
        self._addresses: list[str] = []
        self._rows: dict[str, Adw.ActionRow] = {}
        self._updating = False
        listbox.connect("row-activated", self._on_activated)

    def rebuild(self) -> None:
        self._updating = True
        while (child := self.listbox.get_first_child()) is not None:
            self.listbox.remove(child)
        self._rows.clear()
        self._addresses = list(self.app.manager.services)
        for address in self._addresses:
            row = Adw.ActionRow(activatable=True)
            row.add_css_class("device-row")
            icon = Gtk.Image(icon_name="audio-headphones-symbolic")
            row.add_prefix(icon)
            check = Gtk.Image(icon_name="object-select-symbolic", visible=False)
            row.add_suffix(check)
            row._check = check  # type: ignore[attr-defined]
            self.listbox.append(row)
            self._rows[address] = row
        if not self._addresses:
            empty = Adw.ActionRow(title=_("No earbuds added"), activatable=False)
            empty.add_css_class("dim-label")
            self.listbox.append(empty)
        self._updating = False
        self.update()

    def update(self, address: str | None = None) -> None:
        selected = self.app.manager.selected_address
        for addr, row in self._rows.items():
            if address is not None and addr != address and addr != selected:
                continue
            service = self.app.manager.services.get(addr)
            if service is None:
                continue
            name = service.device.name if service.device else addr
            row.set_title(GLib.markup_escape_text(name))
            row.set_subtitle(GLib.markup_escape_text(battery_summary(service)))
            row._check.set_visible(addr == selected)  # type: ignore[attr-defined]
            if addr == selected and self.listbox.get_selection_mode() != Gtk.SelectionMode.NONE:
                self._updating = True
                self.listbox.select_row(row)
                self._updating = False

    def _on_activated(self, _listbox, row) -> None:
        if self._updating:
            return
        index = row.get_index()
        if 0 <= index < len(self._addresses):
            self.on_chosen(self._addresses[index])


class MainWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.connection_detail = ""
        ui = Ui("window.ui")
        self.ui = ui
        self.window: Adw.ApplicationWindow = ui.get("window", Adw.ApplicationWindow)
        self.window.set_application(app)
        self.window.set_icon_name(app.get_application_id())
        self.split_view = ui.get("split_view", Adw.NavigationSplitView)
        self.nav = ui.get("nav", Adw.NavigationView)
        self.toasts = ui.get("toasts", Adw.ToastOverlay)
        self.background = ui.get("background", Gtk.Box)

        self.sidebar_list = DeviceList(app, ui.get("device_list", Gtk.ListBox), self._choose_from_sidebar)
        ui.get("add_device_button", Gtk.Button).connect("clicked", lambda *_: self.app.show_add_device())
        ui.get("remove_device_button", Gtk.Button).connect("clicked", lambda *_: self.app.confirm_forget_selected())

        self.pages = []
        for cls in PAGES:
            controller = cls(self, Ui(cls.file))
            self.nav.add(controller.page)
            self.pages.append(controller)
        self.home = self.pages[0]
        self.profiles_page = next(p for p in self.pages if p.file == "page-profiles.ui")
        self.nav.replace([self.home.page])
        self._build_selector()

        for name, callback in (
            ("diagnostics", lambda *_: self.app.show_diagnostics()),
            ("refresh", lambda *_: self.app.refresh_devices()),
            ("device-info", lambda *_: self.nav.push_by_tag("about")),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.window.add_action(action)

        self.window.connect("close-request", self._on_close_request)
        # Páginas só se atualizam quando estão à vista: ao aparecer, recuperam o que perderam.
        self._by_page = {p.page: p for p in self.pages}
        for signal in ("notify::visible", "notify::suspended"):
            self.window.connect(signal, lambda *_: self._refresh_shown())
        self.nav.connect("notify::visible-page", lambda *_: self._refresh_shown())
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self._sync_dark())
        self._sync_dark()
        self.apply_background()
        self.devices_changed()
        self.profiles_changed()

    # Seletor de aparelhos no título da tela inicial

    def _build_selector(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("device-popover")
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        box.append(listbox)
        add = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label=_("Add new device")))
        add.add_css_class("flat")
        remove = Gtk.Button(child=Adw.ButtonContent(icon_name="user-trash-symbolic", label=_("Remove devices")))
        remove.add_css_class("flat")
        box.append(add)
        box.append(remove)
        self.popover = Gtk.Popover(child=box)
        self.home.selector.set_popover(self.popover)
        self.selector_list = DeviceList(self.app, listbox, self._choose_from_selector)
        add.connect("clicked", lambda *_: (self.popover.popdown(), self.app.show_add_device()))
        remove.connect("clicked", lambda *_: (self.popover.popdown(), self.app.confirm_forget_selected()))

    def _choose_from_selector(self, address: str) -> None:
        self.popover.popdown()
        self.app.manager.select(address)

    def _choose_from_sidebar(self, address: str) -> None:
        self.app.manager.select(address)
        self.split_view.set_show_content(True)

    # Atualizações

    def present(self) -> None:
        self.window.present()

    def apply_background(self) -> None:
        apply_background(self.background, self.app.config.background)

    def _sync_dark(self) -> None:
        # As variáveis --bs-* do tema escuro ficam sob .dark-theme no style.css.
        if Adw.StyleManager.get_default().get_dark():
            self.window.add_css_class("dark-theme")
        else:
            self.window.remove_css_class("dark-theme")

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=4))

    def devices_changed(self) -> None:
        self.sidebar_list.rebuild()
        self.selector_list.rebuild()
        self.refresh()

    def device_updated(self, address: str) -> None:
        self.sidebar_list.update(address)
        self.selector_list.update(address)

    def selection_changed(self) -> None:
        # Outro fone: volta à tela inicial dele.
        self.nav.pop_to_tag("home")
        self.sidebar_list.update()
        self.selector_list.update()
        self.refresh()

    def profiles_changed(self) -> None:
        self.home.set_profiles([p.name for p in self.app.profiles.profiles])
        self.profiles_page.rebuild()

    def connection_changed(self, state: str, detail: str) -> None:
        self.connection_detail = detail
        self.refresh()

    def refresh(self) -> None:
        for page in self.pages:
            page.refresh()

    def is_shown(self, page) -> bool:
        return (
            self.window.get_visible()
            and not self.window.get_property("suspended")
            and self.nav.get_visible_page() is page.page
        )

    def _refresh_shown(self) -> None:
        page = self._by_page.get(self.nav.get_visible_page())
        if page is not None:
            page.refresh_if_dirty()

    def _on_close_request(self, _window) -> bool:
        if self.app.keep_running_in_background():
            self.window.set_visible(False)
            return True
        return False
