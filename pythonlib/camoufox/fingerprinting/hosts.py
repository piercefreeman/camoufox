from __future__ import annotations

import re
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from random import randint, sample
from typing import Any, ClassVar, TypeVar, cast

from browserforge.fingerprints import ScreenFingerprint
from typing_extensions import Self

from .._generated_profile import (
    AudioProfile,
    CamoufoxProfile,
    CanvasProfile,
    FontsProfile,
    SpeechVoice,
    VoicesProfile,
)
from .common import LINUX, MACOS, HostTargetOS
from .fonts import Font, blocked_families_for_target_os, marker_families_for_target_os
from .voices import (
    Voice,
    blocked_voice_names_for_target_os,
    marker_voice_names_for_target_os,
)

_HOST_ARCH_MAP = {
    "aarch64": "arm64",
    "amd64": "x86_64",
    "arm64": "arm64",
    "i386": "i686",
    "i686": "i686",
    "x86": "x86_64",
    "x86_64": "x86_64",
}

_HOST_TARGET_OS: dict[str, HostTargetOS] = {
    "darwin": MACOS,
    "linux": LINUX,
}

T = TypeVar("T")


@dataclass(frozen=True)
class HostFingerprintAdapter(ABC):
    _cached: ClassVar[HostFingerprintAdapter | None] = None

    architecture: str
    gpu_vendor: str | None
    gpu_family: str | None
    bundled_fonts: tuple[str, ...]
    extra_fonts: tuple[str, ...]
    bundled_voices: tuple[Voice, ...]
    extra_voices: tuple[Voice, ...]

    @classmethod
    def current(cls) -> Self:
        cached = cls._cached
        if cached is None:
            cached = cls._probe()
            cls._cached = cached
        return cast(Self, cached)

    @classmethod
    @abstractmethod
    def _probe(cls) -> Self:
        raise NotImplementedError

    @classmethod
    def filter_locally_installed(cls, fonts: list[Font]) -> list[Font]:
        return cls._filter_locally_installed(fonts, cls._discover_installed_fonts())

    @classmethod
    def filter_locally_available_voices(cls, voices: list[Voice]) -> list[Voice]:
        return cls._filter_locally_available_voices(voices, cls._discover_installed_voices())

    @classmethod
    @abstractmethod
    def _discover_installed_fonts(cls) -> tuple[Font, ...]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _discover_installed_voices(cls) -> tuple[Voice, ...]:
        raise NotImplementedError

    @classmethod
    def _filter_locally_installed(
        cls,
        fonts: list[Font],
        discovered_fonts: tuple[Font, ...],
    ) -> list[Font]:
        return match_installed_fonts(fonts, discovered_fonts)

    @classmethod
    def _filter_locally_available_voices(
        cls,
        voices: list[Voice],
        discovered_voices: tuple[Voice, ...],
    ) -> list[Voice]:
        return match_installed_voices(voices, discovered_voices)

    @property
    @abstractmethod
    def target_os(self) -> HostTargetOS:
        raise NotImplementedError

    @abstractmethod
    def ensure_platform(self, config: CamoufoxProfile) -> None:
        raise NotImplementedError

    @abstractmethod
    def ensure_oscpu(self, config: CamoufoxProfile) -> None:
        raise NotImplementedError

    def adjust_generated_screen(self, screen: ScreenFingerprint) -> None:
        _ = screen

    def normalize_screen(self, config: CamoufoxProfile) -> None:
        _ = config

    def sample_fonts(self) -> list[str]:
        fonts = list(self.bundled_fonts)
        blocked = blocked_families_for_target_os(self.target_os)
        filtered_extras = [family for family in self.extra_fonts if family not in blocked]
        fonts.extend(_sample_extras(filtered_extras))

        installed = set(self.bundled_fonts) | set(self.extra_fonts)
        for marker in marker_families_for_target_os(self.target_os):
            if marker in installed and marker not in fonts:
                fonts.append(marker)

        return _dedupe_list(fonts)

    def sample_voices(self) -> list[str]:
        blocked = blocked_voice_names_for_target_os(self.target_os)
        sampled_voices = [voice.name for voice in self.bundled_voices if voice.name not in blocked]
        sampled_voices.extend(
            voice.name for voice in _sample_extras(self.extra_voices) if voice.name not in blocked
        )

        installed = {voice.name for voice in (*self.bundled_voices, *self.extra_voices)}
        for marker in marker_voice_names_for_target_os(self.target_os):
            if marker in installed and marker not in sampled_voices:
                sampled_voices.append(marker)

        return _dedupe_list(sampled_voices)

    def finalize_config(self, config: CamoufoxProfile) -> None:
        self.ensure_platform(config)
        self.ensure_oscpu(config)
        self.normalize_screen(config)
        _merge_host_inventories(config, self)
        _merge_seed_values(config)


def current_host_target_os() -> HostTargetOS:
    try:
        return _HOST_TARGET_OS[sys.platform]
    except KeyError as error:
        raise NotImplementedError(
            "Camoufox fingerprinting currently ships host adapters only for macOS and Linux."
        ) from error


def normalize_target_os(value: Any | None) -> HostTargetOS:
    host_target_os = current_host_target_os()
    candidates: Sequence[str]
    if value is None:
        candidates = (host_target_os,)
    elif isinstance(value, str):
        candidates = (value,)
    else:
        candidates = tuple(value)

    for candidate in candidates:
        if candidate != host_target_os:
            raise NotImplementedError(
                "Camoufox fingerprinting currently supports only the real host OS. "
                f'Host={host_target_os!r}, requested={candidate!r}.'
            )

    return host_target_os


def get_host_adapter(target_os: Any | None = None) -> HostFingerprintAdapter:
    normalized = normalize_target_os(target_os)
    if normalized == MACOS:
        from .host_macos import MacOSHostAdapter

        return MacOSHostAdapter.current()
    if normalized == LINUX:
        from .host_linux import LinuxHostAdapter

        return LinuxHostAdapter.current()
    raise NotImplementedError(f"Unsupported target OS {normalized!r}.")


def normalize_architecture(machine: str) -> str:
    return _HOST_ARCH_MAP.get(machine.lower(), machine.lower())


def dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def dedupe_list(items: Iterable[str]) -> list[str]:
    return list(dedupe(items))


def sample_extras(items: Sequence[T]) -> list[T]:
    if not items:
        return []

    count = randint(0, min(50, len(items)))  # nosec
    if count == 0:
        return []
    return sample(list(items), count)


def run_host_text(*args: str) -> str:
    result = subprocess.run(
        args,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def normalize_gpu_vendor(text: str) -> str | None:
    lowered = text.lower()
    if "apple" in lowered:
        return "apple"
    if "intel" in lowered:
        return "intel"
    if "nvidia" in lowered:
        return "nvidia"
    if any(marker in lowered for marker in ("amd", "ati", "radeon")):
        return "amd"
    return None


def normalize_gpu_family(text: str) -> str | None:
    lowered = text.lower()
    if not lowered:
        return None
    if re.search(r"apple m[1-9]", lowered):
        return "apple_m_series"
    if "intel(r) hd graphics 400" in lowered:
        return "intel_hd_400"
    if "intel(r) hd graphics" in lowered or "intel hd graphics" in lowered:
        return "intel_hd"
    if "intel iris" in lowered:
        return "intel_iris"
    if "intel arc" in lowered:
        return "intel_arc"
    if "radeon r9 200" in lowered:
        return "amd_radeon_r9_200"
    if "radeon hd 3200" in lowered:
        return "amd_radeon_hd_3200"
    if "geforce gtx 980" in lowered:
        return "nvidia_gtx_980"
    if "geforce gtx 480" in lowered:
        return "nvidia_gtx_480"
    return normalize_gpu_vendor(text)


def match_installed_fonts(fonts: list[Font], discovered_fonts: Sequence[Font]) -> list[Font]:
    index: dict[str, Font] = {}
    for discovered_font in discovered_fonts:
        index.setdefault(discovered_font.family.casefold(), discovered_font)

    matches: list[Font] = []
    for font in fonts:
        installed_font = next(
            (index[name.casefold()] for name in font.names() if name.casefold() in index),
            None,
        )
        if installed_font is None:
            continue
        matches.append(
            Font(
                family=font.family,
                aliases=font.aliases,
                target_os=font.target_os,
                marker=font.marker,
                leak_signal=font.leak_signal,
                path=installed_font.path,
                is_system=installed_font.is_system,
            )
        )
    return matches


def match_installed_voices(voices: list[Voice], discovered_voices: Sequence[Voice]) -> list[Voice]:
    index: dict[str, Voice] = {}
    for discovered_voice in discovered_voices:
        index.setdefault(discovered_voice.name.casefold(), discovered_voice)

    matches: list[Voice] = []
    for voice in voices:
        installed_voice = next(
            (index[name.casefold()] for name in voice.names() if name.casefold() in index),
            None,
        )
        if installed_voice is None:
            continue
        matches.append(
            Voice(
                name=voice.name,
                aliases=voice.aliases,
                target_os=voice.target_os,
                bundled=voice.bundled or installed_voice.bundled,
                marker=voice.marker,
                leak_signal=voice.leak_signal,
            )
        )
    return matches


def _merge_seed_values(config: CamoufoxProfile) -> None:
    config.fonts = config.fonts or FontsProfile()
    config.audio = config.audio or AudioProfile()
    config.canvas = config.canvas or CanvasProfile()
    if config.fonts.spacing_seed is None:
        config.fonts.spacing_seed = randint(1, 4_294_967_295)  # nosec
    if config.audio.seed is None:
        config.audio.seed = randint(1, 4_294_967_295)  # nosec
    if config.canvas.seed is None:
        config.canvas.seed = randint(1, 4_294_967_295)  # nosec


def _merge_host_inventories(config: CamoufoxProfile, host: HostFingerprintAdapter) -> None:
    config.fonts = config.fonts or FontsProfile()
    config.voices = config.voices or VoicesProfile()
    config.fonts.families = host.sample_fonts()
    sampled_voices: list[str | SpeechVoice] = list(host.sample_voices())
    config.voices.items = sampled_voices


_sample_extras = sample_extras
_dedupe_list = dedupe_list
