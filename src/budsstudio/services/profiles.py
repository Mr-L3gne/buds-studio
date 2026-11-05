"""Perfis salvos: combinações de EQ, controle de ruído e ajustes, com nome.

Ficam em $XDG_CONFIG_HOME/buds-studio/profiles.json e podem ser exportados/importados em JSON.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ..i18n import _
from ..protocol import Cap
from ..protocol.messages import BALANCE_MAX, BALANCE_MIN, NoiseControl, Preset
from .config import SYSTEM_EQ_BANDS_HZ, SYSTEM_EQ_GAIN_LIMIT, config_dir
from .fsutil import private_dir, read_json, write_private

FORMAT = "buds-studio-profiles"
FORMAT_VERSION = 1
MAX_NAME_LENGTH = 64
MAX_PROFILES = 100  # limite do arquivo (e do que uma importação pode acrescentar)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)  # True/False não são números aqui


def clean_name(name: str) -> str:
    """Nome sem espaços nas pontas nem caracteres de controle (quebras de linha, ESC etc.)."""
    return "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf", "Cs")).strip()


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    name: str
    preset: int | None = None
    noise_control: int | None = None
    balance: int | None = None
    game_mode: bool | None = None
    system_eq_enabled: bool | None = None
    system_eq_gains: list[float] | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Profile":
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
            raise ProfileError(_("Invalid profile"))
        known = {f.name for f in fields(cls)}
        profile = cls(**{k: v for k, v in raw.items() if k in known})
        profile.name = clean_name(profile.name)
        profile.validate()
        return profile

    def validate(self) -> None:
        def check(ok: bool) -> None:
            if not ok:
                raise ProfileError(_("Invalid value in profile “{name}”").format(name=self.name))

        check(isinstance(self.name, str) and 0 < len(self.name) <= MAX_NAME_LENGTH)
        if self.preset is not None:
            check(_is_int(self.preset) and self.preset in tuple(Preset))
        if self.noise_control is not None:
            check(_is_int(self.noise_control) and self.noise_control in tuple(NoiseControl))
        if self.balance is not None:
            check(_is_int(self.balance) and BALANCE_MIN <= self.balance <= BALANCE_MAX)
        if self.game_mode is not None:
            check(isinstance(self.game_mode, bool))
        if self.system_eq_enabled is not None:
            check(isinstance(self.system_eq_enabled, bool))
        if self.system_eq_gains is not None:
            check(
                isinstance(self.system_eq_gains, list)
                and len(self.system_eq_gains) == len(SYSTEM_EQ_BANDS_HZ)
                and all(
                    isinstance(g, (int, float)) and not isinstance(g, bool) and abs(g) <= SYSTEM_EQ_GAIN_LIMIT
                    for g in self.system_eq_gains
                )
            )


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "profiles.json"
        self.profiles: list[Profile] = []
        self.load()

    def load(self) -> None:
        try:
            self.profiles = self._parse(read_json(self.path))
        except (OSError, ValueError, ProfileError):
            self.profiles = []

    def save(self) -> None:
        private_dir(self.path.parent)
        write_private(self.path, json.dumps(self._dump(self.profiles), indent=2, ensure_ascii=False) + "\n")

    def get(self, name: str) -> Profile | None:
        key = name.strip().casefold()
        return next((p for p in self.profiles if p.name.casefold() == key), None)

    def put(self, profile: Profile) -> None:
        profile.name = clean_name(profile.name)
        profile.validate()
        existing = self.get(profile.name)
        if existing is not None:
            self.profiles[self.profiles.index(existing)] = profile
        elif len(self.profiles) >= MAX_PROFILES:
            raise ProfileError(_("Too many profiles (the limit is {limit})").format(limit=MAX_PROFILES))
        else:
            self.profiles.append(profile)
        self.save()

    def delete(self, name: str) -> None:
        profile = self.get(name)
        if profile is not None:
            self.profiles.remove(profile)
            self.save()

    def export(self, path: Path, names: list[str] | None = None) -> None:
        chosen = [p for p in self.profiles if names is None or p.name in names]
        text = json.dumps(self._dump(chosen), indent=2, ensure_ascii=False) + "\n"
        try:
            write_private(Path(path), text, mode=0o666)  # arquivo para compartilhar: vale o umask do usuário
        except OSError:
            # Pastas do portal de documentos (Flatpak) podem não aceitar o arquivo temporário ao lado.
            Path(path).write_text(text, encoding="utf-8")

    def import_file(self, path: Path) -> list[str]:
        """Importa perfis; os de mesmo nome são substituídos. Devolve os nomes importados."""
        try:
            raw = read_json(Path(path))
        except (OSError, ValueError) as exc:
            raise ProfileError(_("Could not read the file: {error}").format(error=exc)) from exc
        imported = self._parse(raw)
        merged = list(self.profiles)
        for profile in imported:
            existing = next((p for p in merged if p.name.casefold() == profile.name.casefold()), None)
            if existing is not None:
                merged.remove(existing)
            merged.append(profile)
        if len(merged) > MAX_PROFILES:
            raise ProfileError(_("Too many profiles (the limit is {limit})").format(limit=MAX_PROFILES))
        self.profiles = merged
        self.save()
        return [p.name for p in imported]

    @staticmethod
    def _dump(profiles: list[Profile]) -> dict:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "profiles": [{k: v for k, v in asdict(p).items() if v is not None} for p in profiles],
        }

    @staticmethod
    def _parse(raw) -> list[Profile]:
        if not isinstance(raw, dict) or raw.get("format") != FORMAT:
            raise ProfileError(_("This is not a Buds Studio profile file"))
        items = raw.get("profiles")
        if not isinstance(items, list):
            raise ProfileError(_("This is not a Buds Studio profile file"))
        if len(items) > MAX_PROFILES:
            raise ProfileError(_("Too many profiles (the limit is {limit})").format(limit=MAX_PROFILES))
        return [Profile.from_dict(item) for item in items]


def profile_from_current(name: str, device, config) -> Profile:
    """Cria um perfil com o estado atual do fone (e do EQ de sistema)."""
    s = device.state
    return Profile(
        name=name.strip(),
        preset=s.equalizer if device.has(Cap.EQ_PRESETS) else None,
        noise_control=s.noise_control if device.has(Cap.NOISE_CONTROL) else None,
        balance=s.balance if device.has(Cap.BALANCE) else None,
        game_mode=s.game_mode if device.has(Cap.GAME_MODE) else None,
        system_eq_enabled=config.system_eq_enabled,
        system_eq_gains=list(config.system_eq_gains),
    )


def apply_profile(profile: Profile, device, system_eq=None) -> list[str]:
    """Aplica o perfil. Devolve a lista de itens que não puderam ser aplicados."""
    from .device import CommandError

    skipped: list[str] = []

    def attempt(label: str, cap: Cap, call) -> None:
        if not device.has(cap):
            skipped.append(label)
            return
        try:
            call()
        except CommandError:
            skipped.append(label)

    if profile.preset is not None:
        attempt("preset", Cap.EQ_PRESETS, lambda: device.set_preset(profile.preset))
    if profile.noise_control is not None:
        attempt("noise_control", Cap.NOISE_CONTROL, lambda: device.set_noise_control(profile.noise_control))
    if profile.balance is not None:
        attempt("balance", Cap.BALANCE, lambda: device.set_balance(profile.balance))
    if profile.game_mode is not None:
        attempt("game_mode", Cap.GAME_MODE, lambda: device.set_game_mode(profile.game_mode))
    if system_eq is not None and profile.system_eq_enabled is not None:
        if profile.system_eq_gains is not None:
            system_eq.set_gains(profile.system_eq_gains)
        system_eq.set_enabled(profile.system_eq_enabled)
    return skipped
