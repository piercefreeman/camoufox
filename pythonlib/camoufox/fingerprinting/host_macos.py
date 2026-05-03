from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass
from typing import ClassVar, Self

from .._generated_profile import CamoufoxProfile, NavigatorProfile
from .common import HostTargetOS, MACOS
from .fonts import Font, font_definitions_for_target_os
from .voices import Voice, voice_definitions_for_target_os
from .hosts import (
    HostFingerprintAdapter,
    dedupe,
    normalize_architecture,
    normalize_gpu_family,
    normalize_gpu_vendor,
    normalize_target_os,
    run_host_text,
)

_SYSTEM_FONT_PREFIXES = (
    "/System/Library/Fonts",
    "/System/Library/AssetsV2",
    "/Library/Apple/System/Library/Fonts",
)

_COMMON_MACOS_SCREEN_SIZES: tuple[tuple[int, int], ...] = (
    (1280, 800),
    (1440, 900),
    (1512, 982),
    (1680, 1050),
    (1728, 1117),
    (1792, 1120),
    (1920, 1080),
    (2048, 1280),
    (2560, 1600),
    (2560, 1664),
    (3024, 1964),
    (3456, 2234),
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
        matched_catalog_fonts = cls._filter_locally_installed(
            list(font_definitions_for_target_os(MACOS)),
            discovered_fonts,
        )
        matched_catalog_families = {font.family for font in matched_catalog_fonts}
        discovered_voices = cls._discover_installed_voices()
        matched_catalog_voices = cls._filter_locally_available_voices(
            list(voice_definitions_for_target_os(MACOS)),
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
            bundled_voices=_dedupe_voices(bundled_voices),
            extra_voices=_dedupe_voices(extra_voices),
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
        Snap generated macOS screen geometry onto common Apple panel sizes.

        The macOS path is stricter than Linux because real Mac hardware tends to
        cluster around a relatively small set of built-in panel resolutions and
        scaled desktop sizes. BrowserForge can emit geometries that are valid in
        the abstract but unusual for a Mac fingerprint, especially once they are
        combined with our own window overrides or with dimensions inherited from
        a non-macOS execution environment.

        This normalization keeps the claimed macOS profile inside a realistic
        resolution envelope by:
        1. snapping the screen to the nearest known macOS size,
        2. keeping `availWidth` / `availHeight` aligned with that snapped panel,
        3. shrinking outer and inner window dimensions if they would exceed the
           snapped screen while preserving the existing browser-chrome delta.

        We intentionally do not apply the same snapping policy to Linux, where
        real desktops are much less standardized across distributions, display
        servers, and monitor setups.
        """
        if not config.screen:
            return

        width = config.screen.width if isinstance(config.screen.width, int) else None
        height = config.screen.height if isinstance(config.screen.height, int) else None
        if width is None or height is None:
            return

        snapped_width, snapped_height = min(
            _COMMON_MACOS_SCREEN_SIZES,
            key=lambda size: abs(size[0] - width) + abs(size[1] - height),
        )

        config.screen.width = snapped_width
        config.screen.height = snapped_height
        config.screen.avail_width = snapped_width
        config.screen.avail_height = snapped_height

        if not config.window:
            return

        outer_width = config.window.outer_width if isinstance(config.window.outer_width, int) else None
        inner_width = config.window.inner_width if isinstance(config.window.inner_width, int) else None
        if outer_width is not None:
            width_delta = outer_width - inner_width if inner_width is not None else 0
            config.window.outer_width = min(outer_width, snapped_width)
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
            config.window.outer_height = min(outer_height, snapped_height)
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


def _dedupe_voices(voices: list[Voice]) -> tuple[Voice, ...]:
    seen: dict[str, Voice] = {}
    for voice in voices:
        seen.setdefault(voice.name, voice)
    return tuple(seen.values())
