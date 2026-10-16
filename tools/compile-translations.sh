#!/bin/sh
# Compila po/*.po em build/locale, para rodar o app direto do código-fonte.
# Usa o msgfmt do sistema ou, se faltar, o do SDK GNOME (Flatpak).
set -eu
cd "$(dirname "$0")/.."
for lang in $(cat po/LINGUAS); do
    mkdir -p "build/locale/$lang/LC_MESSAGES"
    if command -v msgfmt >/dev/null 2>&1; then
        msgfmt --check -o "build/locale/$lang/LC_MESSAGES/buds-studio.mo" "po/$lang.po"
    else
        flatpak run --filesystem="$PWD" --cwd="$PWD" --command=msgfmt org.gnome.Sdk//51 \
            --check -o "build/locale/$lang/LC_MESSAGES/buds-studio.mo" "po/$lang.po"
    fi
done
