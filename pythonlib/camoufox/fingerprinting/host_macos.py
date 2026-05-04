from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass
from typing import ClassVar

from typing_extensions import Self

from .._generated_profile import CamoufoxProfile, NavigatorProfile
from .common import MACOS, HostTargetOS
from .fonts import Font, default_families_for_target_os
from .hosts import (
    HostFingerprintAdapter,
    dedupe,
    normalize_architecture,
    normalize_gpu_family,
    normalize_gpu_vendor,
    normalize_target_os,
    run_host_text,
)
from .voices import Voice, dedupe_voices, voice_definitions_for_target_os

_SYSTEM_FONT_PREFIXES = (
    "/System/Library/Fonts",
    "/System/Library/AssetsV2",
    "/Library/Apple/System/Library/Fonts",
)


@dataclass(frozen=True)
class MacOSHostAdapter(HostFingerprintAdapter):
    _cached: ClassVar[Self | None] = None

    @property
    def target_os(self) -> HostTargetOS:
        return MACOS

    @classmethod
    def _probe(cls) -> Self:
        normalize_target_os(MACOS)

        discovered_fonts = cls._discover_installed_fonts()
        discovered_voices = cls._discover_installed_voices()
        matched_catalog_voices = cls._filter_locally_available_voices(
            list(voice_definitions_for_target_os(MACOS)),
            discovered_voices,
        )
        matched_catalog_voice_names = {voice.name for voice in matched_catalog_voices}
        gpu_vendor, gpu_family = _probe_gpu_family()

        default_font_families = {
            family.casefold() for family in default_families_for_target_os(MACOS)
        }
        bundled_fonts = [
            font.family for font in discovered_fonts if font.family.casefold() in default_font_families
        ]
        extra_fonts: list[str] = []
        for font in discovered_fonts:
            if font.family.casefold() in default_font_families:
                continue
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
        data = json.loads(run_host_text("system_profiler", "SPFontsDataType", "-json"))
        records: list[Font] = []
        seen: set[str] = set()

        for entry in data.get("SPFontsDataType", []):
            if entry.get("enabled") != "yes":
                continue

            font_path = entry.get("path", "")
            is_system = _is_system_font(font_path)
            for face in entry.get("typefaces", []):
                if face.get("enabled") != "yes" or face.get("valid") == "no":
                    continue
                family = face.get("family")
                if not isinstance(family, str) or family in seen:
                    continue
                seen.add(family)
                records.append(Font(family=family, path=font_path, is_system=is_system))

        return tuple(records)

    @classmethod
    def _discover_installed_voices(cls) -> tuple[Voice, ...]:
        output = run_host_text("say", "-v", "?")
        voices: list[Voice] = []
        seen: set[str] = set()

        for line in output.splitlines():
            match = re.match(r"^(?P<name>.+?)\s{2,}[A-Za-z_]+\s+#", line.rstrip())
            if not match:
                continue
            name = match.group("name").strip()
            if name in seen:
                continue
            seen.add(name)
            voices.append(Voice(name=name, bundled=_is_bundled_voice(name)))

        return tuple(voices)

    def ensure_platform(self, config: CamoufoxProfile) -> None:
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if not config.navigator.platform:
            config.navigator.platform = "MacIntel"

    def ensure_oscpu(self, config: CamoufoxProfile) -> None:
        """
        Fill Firefox's legacy macOS `navigator.oscpu` string when it is absent.

        This field is quirky: on macOS, Firefox historically reports an
        `Intel Mac OS X 10.15`-style token even on newer releases, and a number
        of real-world fingerprints still key off that stable shape rather than
        the underlying host version. BrowserForge or caller presets may omit the
        field entirely, so we patch it in only when the profile already claims a
        macOS Firefox platform (`MacIntel`) and the caller did not explicitly
        supply a value.
        """
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if config.navigator.oscpu:
            return
        if config.navigator.platform == "MacIntel":
            config.navigator.oscpu = "Intel Mac OS X 10.15"

    def normalize_screen(self, config: CamoufoxProfile) -> None:
        """
        Preserve BrowserForge's macOS geometry and only repair impossible values.

        BrowserForge already samples macOS Firefox screens from a mac-specific
        corpus that includes both built-in Apple panel sizes and scaled desktop
        geometries such as `1470x956` and `2056x1329`. Earlier Camoufox builds
        overrode those samples by snapping every macOS screen onto a handpicked
        resolution table, which threw away valid BrowserForge outputs and made
        the paired window dimensions less faithful to the sampled fingerprint.

        The macOS path now trusts BrowserForge's sampled screen and window
        sizes. The only remaining normalization is defensive:
        1. default missing `availWidth` / `availHeight` to the full screen,
        2. clamp `avail*` values so they never exceed the screen,
        3. shrink outer and inner window dimensions if they exceed the screen
           while preserving the existing browser-chrome delta.
        """
        if not config.screen:
            return

        width = config.screen.width if isinstance(config.screen.width, int) else None
        height = config.screen.height if isinstance(config.screen.height, int) else None
        if width is None or height is None:
            return

        avail_width = config.screen.avail_width
        if not isinstance(avail_width, int):
            config.screen.avail_width = width
        else:
            config.screen.avail_width = min(max(avail_width, 0), width)

        avail_height = config.screen.avail_height
        if not isinstance(avail_height, int):
            config.screen.avail_height = height
        else:
            config.screen.avail_height = min(max(avail_height, 0), height)

        if not config.window:
            return

        outer_width = config.window.outer_width if isinstance(config.window.outer_width, int) else None
        inner_width = config.window.inner_width if isinstance(config.window.inner_width, int) else None
        if outer_width is not None:
            width_delta = outer_width - inner_width if inner_width is not None else 0
            config.window.outer_width = min(outer_width, width)
            if inner_width is not None:
                config.window.inner_width = max(config.window.outer_width - width_delta, 0)

        outer_height = (
            config.window.outer_height if isinstance(config.window.outer_height, int) else None
        )
        inner_height = (
            config.window.inner_height if isinstance(config.window.inner_height, int) else None
        )
        if outer_height is not None:
            height_delta = outer_height - inner_height if inner_height is not None else 0
            config.window.outer_height = min(outer_height, height)
            if inner_height is not None:
                config.window.inner_height = max(config.window.outer_height - height_delta, 0)


def _probe_gpu_family() -> tuple[str | None, str | None]:
    data = json.loads(run_host_text("system_profiler", "SPDisplaysDataType", "-json"))
    for entry in data.get("SPDisplaysDataType", []):
        renderer = entry.get("sppci_model") or entry.get("_name") or ""
        vendor = normalize_gpu_vendor(f"{entry.get('spdisplays_vendor', '')} {renderer}")
        family = normalize_gpu_family(renderer)
        return vendor, family
    return None, None


def _is_system_font(font_path: str) -> bool:
    return any(font_path.startswith(prefix) for prefix in _SYSTEM_FONT_PREFIXES)


def _is_bundled_voice(name: str) -> bool:
    lowered = name.lower()
    return "enhanced" not in lowered and "premium" not in lowered and "(" not in lowered
