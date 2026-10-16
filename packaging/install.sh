#!/bin/sh
# Instala o Buds Studio em PREFIX (com DESTDIR opcional). Usado pelo manifesto Flatpak.
#   packaging/install.sh /app
set -eu

PREFIX=${1:?uso: install.sh PREFIX [DESTDIR]}
DESTDIR=${2:-}
APP_ID=io.github.mr_l3gne.BudsStudio
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHARE="$DESTDIR$PREFIX/share"
PKG="$SHARE/buds-studio"

# Código Python
(cd "$ROOT/src" && find budsstudio -name '*.py') | while read -r f; do
    install -D -m 644 "$ROOT/src/$f" "$PKG/$f"
done

# Dados editáveis: layouts, CSS e fundos
for f in "$ROOT"/data/ui/*.ui; do install -D -m 644 "$f" "$PKG/data/ui/$(basename "$f")"; done
install -D -m 644 "$ROOT/data/style.css" "$PKG/data/style.css"
for f in "$ROOT"/data/backgrounds/*; do install -D -m 644 "$f" "$PKG/data/backgrounds/$(basename "$f")"; done
for f in "$ROOT"/data/illustrations/*; do install -D -m 644 "$f" "$PKG/data/illustrations/$(basename "$f")"; done

# Traduções
for lang in $(cat "$ROOT/po/LINGUAS"); do
    install -d "$SHARE/locale/$lang/LC_MESSAGES"
    msgfmt --check -o "$SHARE/locale/$lang/LC_MESSAGES/buds-studio.mo" "$ROOT/po/$lang.po"
done

# Lançador
install -d "$DESTDIR$PREFIX/bin"
cat > "$DESTDIR$PREFIX/bin/buds-studio" <<LAUNCHER
#!/usr/bin/env python3
import sys

sys.path.insert(1, "$PREFIX/share/buds-studio")

from budsstudio.main import main  # noqa: E402

sys.exit(main())
LAUNCHER
chmod 755 "$DESTDIR$PREFIX/bin/buds-studio"

# Integração com o desktop
install -D -m 644 "$ROOT/data/$APP_ID.desktop" "$SHARE/applications/$APP_ID.desktop"
install -D -m 644 "$ROOT/data/$APP_ID.metainfo.xml" "$SHARE/metainfo/$APP_ID.metainfo.xml"
install -D -m 644 "$ROOT/data/icons/$APP_ID.svg" "$SHARE/icons/hicolor/scalable/apps/$APP_ID.svg"
install -D -m 644 "$ROOT/LICENSE" "$SHARE/licenses/$APP_ID/LICENSE"
