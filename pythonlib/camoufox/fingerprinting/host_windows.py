from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from typing import ClassVar

from typing_extensions import Self

from .._generated_profile import CamoufoxProfile, NavigatorProfile
from .common import WINDOWS, HostTargetOS
from .fonts import (
    Font,
    essential_families_for_target_os,
    font_definitions_for_target_os,
)
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

_WINDOWS_FONT_SUFFIXES = {".otf", ".ttc", ".ttf"}
_WINDOWS_BASELINE_FONTS = essential_families_for_target_os(WINDOWS)
_WINDOWS_BUNDLED_VOICE_NAMES = frozenset(
    voice.name for voice in voice_definitions_for_target_os(WINDOWS) if voice.bundled
)

_FONT_STYLE_SUFFIXES = (
    "Bold Italic",
    "Bold Oblique",
    "Semilight Italic",
    "SemiLight Italic",
    "Semibold Italic",
    "SemiBold Italic",
    "Black Italic",
    "Light Italic",
    "Regular",
    "Italic",
    "Bold",
    "Black",
    "Light",
    "Semilight",
    "SemiLight",
    "Semibold",
    "SemiBold",
)

_BUNDLED_FONT_EXACT_FAMILIES: dict[str, tuple[str, ...]] = {
    "bahnschrift": ("Bahnschrift",),
    "cambria": ("Cambria", "Cambria Math"),
    "ebrima": ("Ebrima",),
    "ebrimabd": ("Ebrima",),
    "gabriola": ("Gabriola",),
    "gadugi": ("Gadugi",),
    "gadugib": ("Gadugi",),
    "himalaya": ("Microsoft Himalaya",),
    "holomdl2": ("HoloLens MDL2 Assets",),
    "impact": ("Impact",),
    "inkfree": ("Ink Free",),
    "javatext": ("Javanese Text",),
    "lucon": ("Lucida Console",),
    "marlett": ("Marlett",),
    "micross": ("Microsoft Sans Serif",),
    "mingliub": ("MingLiU-ExtB",),
    "monbaiti": ("Mongolian Baiti",),
    "msgothic": ("MS Gothic",),
    "mvboli": ("MV Boli",),
    "segmdl2": ("Segoe MDL2 Assets",),
    "segoeicons": ("Segoe Fluent Icons",),
    "seguiemj": ("Segoe UI Emoji",),
    "seguihis": ("Segoe UI Historic",),
    "seguisym": ("Segoe UI Symbol",),
    "simsun": ("SimSun",),
    "simsunb": ("SimSun-ExtB",),
    "sitkavf": ("Sitka",),
    "sitkavf-italic": ("Sitka",),
    "sylfaen": ("Sylfaen",),
    "symbol": ("Symbol",),
    "webdings": ("Webdings",),
    "wingding": ("Wingdings",),
}

_BUNDLED_FONT_PREFIX_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("arial", ("Arial",)),
    ("calibri", ("Calibri",)),
    ("cambria", ("Cambria",)),
    ("candara", ("Candara",)),
    ("comic", ("Comic Sans MS",)),
    ("consola", ("Consolas",)),
    ("constan", ("Constantia",)),
    ("corbel", ("Corbel",)),
    ("cour", ("Courier New",)),
    ("framd", ("Franklin Gothic Medium",)),
    ("georgia", ("Georgia",)),
    ("leel", ("Leelawadee UI",)),
    ("malgun", ("Malgun Gothic",)),
    ("mmrtext", ("Myanmar Text",)),
    ("msjh", ("Microsoft JhengHei",)),
    ("msyh", ("Microsoft YaHei",)),
    ("msyi", ("Microsoft Yi Baiti",)),
    ("nirmala", ("Nirmala UI",)),
    ("ntailu", ("Microsoft New Tai Lue",)),
    ("pala", ("Palatino Linotype",)),
    ("phagspa", ("Microsoft PhagsPa",)),
    ("segoepr", ("Segoe Print",)),
    ("segoesc", ("Segoe Script",)),
    ("segoeui", ("Segoe UI",)),
    ("segui", ("Segoe UI",)),
    ("tahoma", ("Tahoma",)),
    ("taile", ("Microsoft Tai Le",)),
    ("times", ("Times New Roman",)),
    ("trebuc", ("Trebuchet MS",)),
    ("verdana", ("Verdana",)),
    ("yugoth", ("Yu Gothic",)),
)


@dataclass(frozen=True)
class WindowsHostAdapter(HostFingerprintAdapter):
    _cached: ClassVar[Self | None] = None

    @property
    def target_os(self) -> HostTargetOS:
        return WINDOWS

    @classmethod
    def _probe(cls) -> Self:
        normalize_target_os(WINDOWS)

        discovered_fonts = cls._discover_installed_fonts()
        matched_catalog_fonts = cls._filter_locally_installed(
            list(font_definitions_for_target_os(WINDOWS)),
            discovered_fonts,
        )
        matched_catalog_families = {font.family for font in matched_catalog_fonts}
        discovered_voices = cls._discover_installed_voices()
        matched_catalog_voices = cls._filter_locally_available_voices(
            list(voice_definitions_for_target_os(WINDOWS)),
            discovered_voices,
        )
        matched_catalog_voice_names = {voice.name for voice in matched_catalog_voices}
        gpu_vendor, gpu_family = _probe_gpu_family()

        bundled_fonts = [font.family for font in matched_catalog_fonts if _is_baseline_font(font.family)]
        extra_fonts = [font.family for font in matched_catalog_fonts if not _is_baseline_font(font.family)]
        for font in discovered_fonts:
            if font.family in matched_catalog_families:
                continue
            if _is_baseline_font(font.family):
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
        for probe in (_discover_registry_fonts, _discover_bundled_runtime_fonts):
            try:
                fonts = probe()
            except (CalledProcessError, FileNotFoundError):
                continue
            if fonts:
                return fonts
        return ()

    @classmethod
    def _discover_installed_voices(cls) -> tuple[Voice, ...]:
        for probe in (_discover_sapi_voices, _discover_registry_voices):
            try:
                voices = probe()
            except (CalledProcessError, FileNotFoundError):
                continue
            if voices:
                return voices
        return ()

    def ensure_platform(self, config: CamoufoxProfile) -> None:
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if not config.navigator.platform:
            config.navigator.platform = "Win32"

    def ensure_oscpu(self, config: CamoufoxProfile) -> None:
        if not config.navigator:
            config.navigator = NavigatorProfile()
        if config.navigator.oscpu:
            return
        if (config.navigator.platform or "Win32").startswith("Win"):
            config.navigator.oscpu = _default_oscpu(self.architecture)

    def normalize_screen(self, config: CamoufoxProfile) -> None:
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


def _discover_registry_fonts() -> tuple[Font, ...]:
    output = _run_powershell(
        r"""
$roots = @(
  @{ Hive = 'HKLM'; Path = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts' },
  @{ Hive = 'HKCU'; Path = 'HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts' }
)
foreach ($root in $roots) {
  if (Test-Path $root.Path) {
    $item = Get-ItemProperty -Path $root.Path
    foreach ($property in $item.PSObject.Properties) {
      if ($property.MemberType -eq 'NoteProperty' -and $property.Name -notlike 'PS*') {
        "{0}`t{1}`t{2}" -f $root.Hive, $property.Name, $property.Value
      }
    }
  }
}
""".strip()
    )

    records: list[Font] = []
    seen: set[str] = set()
    for line in output.splitlines():
        try:
            hive, display_name, font_path = line.split("\t", 2)
        except ValueError:
            continue

        is_system = hive == "HKLM" and not _is_user_font_path(font_path)
        for family in _families_from_registry_name(display_name):
            if family in seen:
                continue
            seen.add(family)
            records.append(
                Font(
                    family=family,
                    path=_normalize_windows_font_path(font_path),
                    is_system=is_system,
                )
            )
    return tuple(records)


def _discover_bundled_runtime_fonts() -> tuple[Font, ...]:
    for font_dir in _runtime_font_dir_candidates():
        if not font_dir.is_dir():
            continue

        font_paths = [
            path
            for path in sorted(font_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in _WINDOWS_FONT_SUFFIXES
        ]
        if not font_paths:
            continue

        records: list[Font] = []
        seen: set[str] = set()
        for path in font_paths:
            for family in _families_from_bundled_filename(path):
                if family in seen:
                    continue
                seen.add(family)
                records.append(Font(family=family, path=str(path), is_system=True))
        if records:
            return tuple(records)
    return ()


def _discover_sapi_voices() -> tuple[Voice, ...]:
    output = _run_powershell(
        r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() |
  Where-Object { $_.Enabled } |
  ForEach-Object { $_.VoiceInfo.Name }
""".strip()
    )
    return _parse_voice_names(output.splitlines())


def _discover_registry_voices() -> tuple[Voice, ...]:
    output = _run_powershell(
        r"""
$paths = @(
  'HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens',
  'HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens',
  'HKCU:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens',
  'HKCU:\SOFTWARE\Microsoft\Speech\Voices\Tokens'
)
foreach ($path in $paths) {
  if (Test-Path $path) {
    Get-ChildItem $path | ForEach-Object {
      $item = Get-ItemProperty $_.PSPath
      if ($item.Name) { $item.Name }
    }
  }
}
""".strip()
    )
    return _parse_voice_names(output.splitlines())


def _probe_gpu_family() -> tuple[str | None, str | None]:
    for probe in (_probe_gpu_from_cim, _probe_gpu_from_wmic):
        try:
            gpu = probe()
        except (CalledProcessError, FileNotFoundError):
            continue
        if gpu != (None, None):
            return gpu
    return None, None


def _probe_gpu_from_cim() -> tuple[str | None, str | None]:
    output = _run_powershell(
        "(Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.Name } | "
        "Select-Object -First 1 -ExpandProperty Name)"
    )
    renderer = output.strip().splitlines()[0] if output.strip() else ""
    if renderer:
        return normalize_gpu_vendor(renderer), normalize_gpu_family(renderer)
    return None, None


def _probe_gpu_from_wmic() -> tuple[str | None, str | None]:
    output = run_host_text("wmic", "path", "win32_VideoController", "get", "name")
    for line in output.splitlines():
        renderer = line.strip()
        if not renderer or renderer.lower() == "name":
            continue
        return normalize_gpu_vendor(renderer), normalize_gpu_family(renderer)
    return None, None


def _run_powershell(script: str) -> str:
    last_error: CalledProcessError | FileNotFoundError | None = None
    for executable in ("powershell.exe", "powershell", "pwsh"):
        try:
            return run_host_text(
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            )
        except (CalledProcessError, FileNotFoundError) as error:
            last_error = error
    if last_error is not None:
        raise last_error
    return ""


def _families_from_registry_name(display_name: str) -> tuple[str, ...]:
    base = re.sub(r"\s+\([^)]+\)\s*$", "", display_name).strip()
    families: list[str] = []
    for part in re.split(r"\s*&\s*", base):
        family = _strip_font_style_suffix(part.lstrip("@").strip())
        if family:
            families.append(family)
    return tuple(dict.fromkeys(families))


def _strip_font_style_suffix(name: str) -> str:
    family = name
    while True:
        lowered = family.casefold()
        for suffix in _FONT_STYLE_SUFFIXES:
            suffix_token = f" {suffix.casefold()}"
            if lowered.endswith(suffix_token):
                family = family[: -len(suffix_token)].strip()
                break
        else:
            return family


def _families_from_bundled_filename(path: Path) -> tuple[str, ...]:
    stem = path.stem.casefold()
    exact = _BUNDLED_FONT_EXACT_FAMILIES.get(stem)
    if exact is not None:
        return exact

    for prefix, families in _BUNDLED_FONT_PREFIX_FAMILIES:
        if stem.startswith(prefix):
            return families
    return ()


def _runtime_font_dir_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = [Path(__file__).resolve().parents[3] / "bundle" / "fonts" / "windows"]

    try:
        from ..pkgman import OS_NAME, camoufox_path

        install_root = camoufox_path(download_if_missing=False)
        if OS_NAME == "mac":
            candidates.append(
                install_root / "Camoufox.app" / "Contents" / "Resources" / "fonts" / "windows"
            )
        else:
            candidates.append(install_root / "fonts" / "windows")
    except Exception:
        pass

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return tuple(deduped)


def _parse_voice_names(lines: list[str]) -> tuple[Voice, ...]:
    voices: list[Voice] = []
    seen: set[str] = set()
    for line in lines:
        name = line.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        voices.append(Voice(name=name, bundled=name in _WINDOWS_BUNDLED_VOICE_NAMES))
    return tuple(voices)


def _normalize_windows_font_path(font_path: str) -> str:
    path = font_path.strip()
    if not path:
        return path

    expanded = os.path.expandvars(path)
    if re.match(r"^[a-zA-Z]:[\\/]", expanded) or expanded.startswith("\\\\"):
        return expanded

    windows_dir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return str(Path(windows_dir) / "Fonts" / expanded)


def _is_user_font_path(font_path: str) -> bool:
    normalized = font_path.replace("/", "\\").casefold()
    return (
        "%localappdata%" in normalized
        or "%appdata%" in normalized
        or ("\\users\\" in normalized and "\\appdata\\" in normalized)
    )


def _is_baseline_font(family: str) -> bool:
    return family in _WINDOWS_BASELINE_FONTS


def _default_oscpu(architecture: str) -> str:
    if architecture == "i686":
        return "Windows NT 10.0"
    if architecture == "arm64":
        return "Windows NT 10.0; Win64; ARM64"
    return "Windows NT 10.0; Win64; x64"
