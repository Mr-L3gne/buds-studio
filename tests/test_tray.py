"""Bandeja: formato do layout do com.canonical.dbusmenu (sem D-Bus)."""

import unittest

import frames  # noqa: F401  (põe src/ no sys.path)

from budsstudio.services.tray import MenuItem, TrayIcon

LAYOUT = "(ia{sv}av)"


def menu() -> list[MenuItem]:
    return [
        MenuItem("Fone: E 90% · D 80%", enabled=False),
        MenuItem(separator=True),
        MenuItem("Equalizador", children=[MenuItem("Normal", radio=True), MenuItem("Graves", radio=False)]),
        MenuItem("Sair", lambda: None),
    ]


class TrayLayoutTest(unittest.TestCase):
    def assert_layout(self, variant, depth=0):
        self.assertEqual(variant.get_type_string(), LAYOUT)
        children = variant.get_child_value(2)
        for i in range(children.n_children()):
            boxed = children.get_child_value(i)
            self.assertEqual(boxed.get_type_string(), "v")
            # Um só nível de variant: o host (ex.: extensão AppIndicator do GNOME) desempacota
            # cada filho esperando (ia{sv}av). Com v dentro de v, ele lança TypeError, recria o
            # cliente do menu e pede o layout de novo, sem parar (~230 GetLayout/s).
            self.assert_layout(boxed.get_variant(), depth + 1)

    def test_layout_children_are_single_boxed(self):
        tray = TrayIcon(lambda: None)
        tray.update("Buds Studio", "", menu())
        self.assert_layout(tray._layout(tray._root, -1))

    def test_partial_depth(self):
        tray = TrayIcon(lambda: None)
        tray.update("Buds Studio", "", menu())
        layout = tray._layout(tray._root, 1)
        self.assert_layout(layout)
        eq = layout.get_child_value(2).get_child_value(2).get_variant()
        self.assertEqual(eq.get_child_value(2).n_children(), 0)


if __name__ == "__main__":
    unittest.main()
