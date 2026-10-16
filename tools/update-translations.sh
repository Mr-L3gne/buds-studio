#!/bin/sh
# Extrai as strings (po/buds-studio.pot) e atualiza po/*.po. Precisa do gettext (ou do SDK GNOME).
set -eu
cd "$(dirname "$0")/.."
find src/budsstudio -name '*.py' | sort > po/POTFILES
ls data/ui/*.ui >> po/POTFILES
run() { if command -v xgettext >/dev/null 2>&1; then sh -c "$1"; else
    flatpak run --filesystem="$PWD" --cwd="$PWD" --command=sh org.gnome.Sdk//51 -c "$1"; fi; }
run 'xgettext --from-code=UTF-8 --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --package-name=buds-studio -o po/buds-studio.pot -L Python $(grep "\.py$" po/POTFILES) && xgettext --from-code=UTF-8 -j -o po/buds-studio.pot -L Glade $(grep "\.ui$" po/POTFILES) && for l in $(cat po/LINGUAS); do msgmerge -q --update --backup=none po/$l.po po/buds-studio.pot; done'
