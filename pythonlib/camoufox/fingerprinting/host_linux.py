from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from typing import ClassVar, Self

from .._generated_profile import CamoufoxProfile, NavigatorProfile
from .common import HostTargetOS, LINUX
from .fonts import Font, font_definitions_for_target_os
from .voices import Voice, dedupe_voices, voice_definitions_for_target_os
from .hosts import (
    HostFingerprintAdapter,
    dedupe,
    normalize_architecture,
    normalize_gpu_family,
    normalize_gpu_vendor,
    normalize_target_os,
    run_host_text,
)


@dataclass(frozen=True)
class LinuxHostAdapter(HostFingerprintAdapter):
    _cached: ClassVar[Self | None] = None

    @property
    def target_os(self) -> HostTargetOS:
        return LINUX

    @classmethod
    def _probe(cls) -> Self:
        normalize_target_os(LINUX)

        discovered_fonts = cls._discover_installed_fonts()
        matched_catalog_fonts = cls._filter_locally_installed(
            list(font_definitions_for_target_os(LINUX)),
            discovered_fonts,
        )
        matched_catalog_families = {font.family for font in matched_catalog_fonts}
        discovered_voices = cls._discover_installed_voices()
        matched_catalog_voices = cls._filter_locally_available_voices(
            list(voice_definitions_for_target_os(LINUX)),
            discovered_voices,
        )
        matched_catalog_voice_names = {voice.name for voice in matched_catalog_voices}
        gpu_vendor, gpu_family = _probe_gpu_family()

        bundled_fonts = [font.family for font in matched_catalog_fonts if font.is_system]
        extra_fonts = [font.family for font in matched_catalog_fonts if not font.is_system]
        for font in discovered_fonts:
            if font.family in matched_catalog_families:
                continue
            if font.is_system:
                bundled_fonts.append(font.family)
            else:
                extra_fonts.append(font.family)

        bundled_voices = [voice for voice in matched_catalog_voices if voice.bundled]
        extra_voices = [voice for voice in matched_catalog_voices if not voice.bundled]
        for voice in discovered_voices:
            if voice.name in matched_catalog_voice_names:
                continue
            if voice.bundled:
                bundled_voices.append(voice)
            else:
                extra_voices.append(voice)

        return cls(
            architecture=normalize_architecture(platform.machine()),
            gpu_vendor=gpu_vendor,
            gpu_family=gpu_family,
            bundled_fonts=dedupe(bundled_fonts),
            extra_fonts=dedupe(extra_fonts),
            bundled_voices=dedupe_voices(bundled_voices),
            extra_voices=dedupe_voices(extra_voices),
        )

    @classmethod
    def _discover_installed_fonts(cls) -> tuple[Font, ...]:
        output = run_host_text("fc-list", "--format", "%{family}\t%{file}\n")
        records: list[Font] = []
        seen: set[str] = set()

        for line in output.splitlines():
            try:
                families_part, font_path = line.rsplit("\t", 1)
            except ValueError:
                continue

            is_system = _is_system_font(font_path)
            for family in [part.strip() for part in families_part.split(",") if part.strip()]:
                if family in seen:
                    continue
                seen.add(family)
                records.append(Font(family=family, path=font_path, is_system=is_system))

        return tuple(records)

    @classmethod
    def _discover_installed_voices(cls) -> tuple[Voice, ...]:
        for command in (("espeak-ng", "--voices"), ("espeak", "--voices")):
            try:
                output = run_host_text(*command)
            except (CalledProcessError, FileNotFoundError):
                continue
            voices = _parse_espeak_voices(output)
            if voices:
                return tuple(voices)
        return ()

    def ensure_platform(self, config: CamoufoxProfile) -> None:
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if not config.navigator.platform:
            config.navigator.platform = f"Linux {self.architecture}"

    def ensure_oscpu(self, config: CamoufoxProfile) -> None:
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if config.navigator.oscpu:
            return
        platform_value = config.navigator.platform or f"Linux {self.architecture}"
        if "Linux" in platform_value:
            config.navigator.oscpu = platform_value


def _probe_gpu_family() -> tuple[str | None, str | None]:
    for probe in (_probe_gpu_from_lspci, _probe_gpu_from_glxinfo):
        try:
            gpu = probe()
        except (CalledProcessError, FileNotFoundError):
            continue
        if gpu != (None, None):
            return gpu
    return None, None


def _probe_gpu_from_lspci() -> tuple[str | None, str | None]:
    output = run_host_text("lspci")
    for line in output.splitlines():
        if not re.search(r"(VGA compatible controller|3D controller|Display controller)", line):
            continue
        renderer = line.split(":", 2)[-1].strip()
        vendor = normalize_gpu_vendor(renderer)
        family = normalize_gpu_family(renderer)
        return vendor, family
    return None, None


def _probe_gpu_from_glxinfo() -> tuple[str | None, str | None]:
    output = run_host_text("glxinfo", "-B")
    vendor = None
    renderer = ""
    for line in output.splitlines():
        if "OpenGL vendor string:" in line:
            vendor = normalize_gpu_vendor(line.split(":", 1)[1].strip())
        elif "OpenGL renderer string:" in line:
            renderer = line.split(":", 1)[1].strip()
    if renderer:
        return vendor or normalize_gpu_vendor(renderer), normalize_gpu_family(renderer)
    return None, None


def _parse_espeak_voices(output: str) -> list[Voice]:
    voices: list[Voice] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.rstrip()
        if not line or line.startswith("Pty "):
            continue
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=4)
        if len(parts) < 4:
            continue
        name = parts[3].strip()
        if name in seen:
            continue
        seen.add(name)
        voices.append(Voice(name=name, bundled=True))
    return voices


def _is_system_font(font_path: str) -> bool:
    home = str(Path.home())
    user_prefixes = (
        f"{home}/.fonts",
        f"{home}/.local/share/fonts",
    )
    return not any(font_path.startswith(prefix) for prefix in user_prefixes)
