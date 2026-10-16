"""Tradução via gettext. Português do Brasil é o padrão; inglês é o idioma do código-fonte.

A escolha fica em `config.json` (`language`: "pt_BR", "en" ou "auto"). Ela é aplicada pela
variável LANGUAGE antes de o GTK iniciar, para que os arquivos .ui também sejam traduzidos.
"""

from __future__ import annotations

import gettext
import locale
import os
from pathlib import Path

from . import GETTEXT_DOMAIN

SUPPORTED = ("pt_BR", "en")
DEFAULT_LANGUAGE = "pt_BR"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def locale_dir() -> str:
    env = os.environ.get("BUDS_STUDIO_LOCALEDIR")
    if env:
        return env
    here = Path(__file__).resolve().parent
    # Instalado: <prefix>/share/buds-studio/budsstudio → <prefix>/share/locale
    installed = here.parent.parent / "locale"
    if installed.is_dir():
        return str(installed)
    # Código-fonte: <repo>/build/locale (gerado por `tools/compile-translations.sh`)
    return str(here.parent.parent / "build" / "locale")


def resolve_language(choice: str | None) -> str:
    if choice in SUPPORTED:
        return choice
    if choice == "auto":
        for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(var, "")
            if value:
                return "en" if value.startswith("en") else DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


def setup(choice: str | None = None) -> str:
    global _translation
    language = resolve_language(choice)
    os.environ["LANGUAGE"] = language
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    # Com LC_MESSAGES = C a glibc ignora LANGUAGE; troca por um locale UTF-8 existente.
    if locale.setlocale(locale.LC_MESSAGES) in ("C", "POSIX", "C.UTF-8", "C.utf8"):
        for candidate in ("pt_BR.UTF-8", "en_US.UTF-8", "C.UTF-8"):
            try:
                locale.setlocale(locale.LC_MESSAGES, candidate)
                break
            except locale.Error:
                continue
    directory = locale_dir()
    if hasattr(locale, "bindtextdomain"):
        locale.bindtextdomain(GETTEXT_DOMAIN, directory)
        locale.textdomain(GETTEXT_DOMAIN)
    _translation = gettext.translation(
        GETTEXT_DOMAIN, directory, languages=[language], fallback=True
    )
    return language


def N_(message: str) -> str:
    """Marca o texto para extração sem traduzir agora."""
    return message


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)
