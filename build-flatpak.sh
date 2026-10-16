#!/bin/sh
# Compila o Buds Studio como Flatpak, instala para o usuário (--user) e gera
# dist/buds-studio.flatpak para instalar em outra máquina ou compartilhar.
#
# Requisitos: flatpak, o remoto flathub e o flatpak-builder (nativo ou o app
# org.flatpak.Builder). O script instala o runtime/SDK GNOME 51 se faltarem.
set -eu

cd "$(dirname "$0")"
APP_ID=io.github.mr_l3gne.BudsStudio
MANIFEST="$APP_ID.yml"
BUILD_DIR=build-dir
REPO=repo
BUNDLE=dist/buds-studio.flatpak

if command -v flatpak-builder >/dev/null 2>&1; then
    BUILDER="flatpak-builder"
elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
    BUILDER="flatpak run org.flatpak.Builder"
else
    echo "Instalando o org.flatpak.Builder…"
    flatpak install --user -y flathub org.flatpak.Builder
    BUILDER="flatpak run org.flatpak.Builder"
fi

flatpak install --user -y --noninteractive flathub org.gnome.Platform//51 org.gnome.Sdk//51 >/dev/null 2>&1 || true

$BUILDER --user --install --force-clean --repo="$REPO" --install-deps-from=flathub "$BUILD_DIR" "$MANIFEST"

mkdir -p dist
flatpak build-bundle "$REPO" "$BUNDLE" "$APP_ID" --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo

echo
echo "Instalado. Abra com:  flatpak run $APP_ID"
echo "Pacote para compartilhar: $BUNDLE  (instale com: flatpak install --user $BUNDLE)"
