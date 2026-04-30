from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from random import randint, randrange, sample
from typing import Any, ClassVar, cast

from browserforge.fingerprints import (
    Fingerprint,
    FingerprintGenerator,
    ScreenFingerprint,
)

from ._generated_profile import (
    AudioProfile,
    CamoufoxProfile,
    CanvasProfile,
    FontsProfile,
    LocaleProfile,
    NavigatorProfile,
    ScreenProfile,
    SpeechVoice,
    VoicesProfile,
    WindowProfile,
)

_GENERATED_FINGERPRINT_IDS: set[int] = set()


def generate_context_fingerprint(
    fingerprint: Fingerprint | None = None,
    preset: dict[str, Any] | None = None,
    os: str | None = None,
    ff_version: str | None = None,
    webrtc_ip: str | None = None,
    timezone: str | None = None,
    locale: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """
    Build the per-context fingerprint payload used by `BrowserContext.add_init_script()`.

    When `preset` is omitted, BrowserForge generates the Firefox/macOS
    skeleton and Camoufox normalizes it into a smaller host-compatible config.
    When `fingerprint` is provided, that BrowserForge fingerprint is reused
    directly so the caller can keep browser-launch and per-context geometry in
    sync.
    When `preset` is provided, the preset is treated as an explicit caller
    override and compiled through the same host-compatibility layer.

    Returns a dictionary with:
    - `config`: the final generated CamoufoxProfile
    - `context_options`: the Playwright context kwargs derived from that config
    - `init_script`: the JavaScript initializer that applies per-context values
    """
    compiler = _FirefoxFingerprintCompiler.current()
    _debug_log(debug, "Preparing fingerprinted browser context.")

    if fingerprint is not None and preset is not None:
        raise ValueError("Pass either `fingerprint` or `preset`, not both.")

    if fingerprint is not None:
        _debug_log(debug, "Reusing caller-supplied BrowserForge fingerprint.")
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    elif preset is None:
        _debug_log(debug, "Generating BrowserForge Firefox skeleton.")
        fingerprint = generate_fingerprint(os=os, debug=debug)
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    else:
        _debug_log(debug, "Compiling explicit preset through the host-compatibility layer.")
        config = compiler.compile_preset(preset, ff_version)
        screen = compiler.screen_from_preset(preset, config)

    if timezone:
        config.timezone = timezone
    if locale:
        _apply_locale_override(config, locale)

    context_options = compiler.build_context_options(config, screen)
    _debug_log(
        debug,
        "Fingerprint ready: "
        f"screen={screen.width}x{screen.height}, "
        f"fonts={len(config.fonts.families) if config.fonts and config.fonts.families else 0}, "
        f"voices={len(config.voices.items) if config.voices and config.voices.items else 0}, "
        f"timezone={config.timezone or 'system'}",
    )
    _debug_log(debug, f"Context options ready: {context_options}")

    return {
        "init_script": compiler.build_init_script(config, screen, webrtc_ip),
        "context_options": context_options,
        "config": config,
        "preset": preset,
    }


def generate_fingerprint(
    window: tuple[int, int] | None = None,
    debug: bool = False,
    **config: Any,
) -> Fingerprint:
    """
    Generate a BrowserForge Firefox fingerprint constrained to the real macOS host.

    This is the lowest-level public constructor for the active fingerprint flow.
    The generated object still looks like BrowserForge output; call
    `from_browserforge()` to compile it into a Camoufox config map.
    """
    _debug_log(debug, f"Requesting BrowserForge fingerprint for os={config.get('os') or 'macos'}.")
    fingerprint = _FirefoxFingerprintCompiler.current().generate(window=window, **config)
    _GENERATED_FINGERPRINT_IDS.add(id(fingerprint))
    _debug_log(debug, "BrowserForge fingerprint generated successfully.")
    return fingerprint


def from_browserforge(fingerprint: Fingerprint, ff_version: str | None = None) -> CamoufoxProfile:
    """
    Compile a BrowserForge fingerprint into a host-compatible `CamoufoxProfile`.

    Only a small set of values are carried forward: Firefox navigator fields,
    screen/window geometry, timezone/locale, noise seeds, and the sampled font
    and voice inventories that are actually present on the local macOS host.
    """
    return _FirefoxFingerprintCompiler.current().compile_browserforge(fingerprint, ff_version)


def from_preset(preset: dict[str, Any], ff_version: str | None = None) -> CamoufoxProfile:
    """
    Compile an explicit caller-supplied preset into a host-compatible `CamoufoxProfile`.

    This path exists for callers that already have a preset dictionary and want
    Camoufox to normalize it the same way as BrowserForge output. Camoufox no
    longer ships a bundled preset corpus.
    """
    return _FirefoxFingerprintCompiler.current().compile_preset(preset, ff_version)


def is_generated_fingerprint(fingerprint: Fingerprint) -> bool:
    """
    Return whether a fingerprint was produced by Camoufox's BrowserForge helper.
    """
    return id(fingerprint) in _GENERATED_FINGERPRINT_IDS


def _debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[camoufox:fingerprint] {message}")


_HOST_ARCH_MAP = {
    "aarch64": "arm64",
    "amd64": "x86_64",
    "arm64": "arm64",
    "i386": "i686",
    "i686": "i686",
    "x86": "x86_64",
    "x86_64": "x86_64",
}

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

_MACOS_MARKER_FONTS = ("Helvetica Neue", "PingFang HK", "PingFang SC", "PingFang TC")


@dataclass(frozen=True)
class _CompiledScreen:
    width: int | None
    height: int | None
    color_depth: int | None
    device_pixel_ratio: float | None = None


@dataclass(frozen=True)
class _FontRecord:
    family: str
    path: str


@dataclass(frozen=True)
class _MacOSHostProfile:
    architecture: str
    gpu_vendor: str | None
    gpu_family: str | None
    bundled_fonts: tuple[str, ...]
    extra_fonts: tuple[str, ...]
    bundled_voices: tuple[str, ...]
    extra_voices: tuple[str, ...]

    _cached: ClassVar[_MacOSHostProfile | None] = None

    @classmethod
    def current(cls) -> _MacOSHostProfile:
        if cls._cached is None:
            cls._cached = cls._probe()
        return cls._cached

    @classmethod
    def _probe(cls) -> _MacOSHostProfile:
        _normalize_target_os("macos")

        gpu_vendor, gpu_family = _probe_gpu_family()
        fonts = _probe_fonts()
        voices = _probe_voices()

        bundled_fonts = tuple(record.family for record in fonts if _is_system_font(record.path))
        extra_fonts = tuple(record.family for record in fonts if not _is_system_font(record.path))
        bundled_voices = tuple(name for name in voices if _is_bundled_voice(name))
        extra_voices = tuple(name for name in voices if not _is_bundled_voice(name))

        return cls(
            architecture=_normalize_architecture(platform.machine()),
            gpu_vendor=gpu_vendor,
            gpu_family=gpu_family,
            bundled_fonts=_dedupe(bundled_fonts),
            extra_fonts=_dedupe(extra_fonts),
            bundled_voices=_dedupe(bundled_voices),
            extra_voices=_dedupe(extra_voices),
        )

    def sample_fonts(self) -> list[str]:
        fonts = list(self.bundled_fonts)
        fonts.extend(_sample_extras(self.extra_fonts))
        for marker in _MACOS_MARKER_FONTS:
            if marker in self.bundled_fonts and marker not in fonts:
                fonts.append(marker)
        return _dedupe_list(fonts)

    def sample_voices(self) -> list[str]:
        voices = list(self.bundled_voices)
        voices.extend(_sample_extras(self.extra_voices))
        return _dedupe_list(voices)


@dataclass(frozen=True)
class _FirefoxFingerprintCompiler:
    generator: FingerprintGenerator

    _cached: ClassVar[_FirefoxFingerprintCompiler | None] = None

    @classmethod
    def current(cls) -> _FirefoxFingerprintCompiler:
        if cls._cached is None:
            cls._cached = cls(generator=FingerprintGenerator(browser="firefox", os=("macos",)))
        return cls._cached

    def generate(self, window: tuple[int, int] | None = None, **config: Any) -> Fingerprint:
        config["os"] = _normalize_target_os(config.get("os"))
        fingerprint = self.generator.generate(**config)
        if window:
            _apply_window_override(fingerprint, *window)
        return fingerprint

    def compile_browserforge(
        self,
        fingerprint: Fingerprint,
        ff_version: str | None,
    ) -> CamoufoxProfile:
        source = asdict(fingerprint)
        navigator = source.get("navigator", {})
        screen = asdict(fingerprint.screen)

        profile = CamoufoxProfile(
            navigator=_navigator_from_browserforge(navigator, ff_version),
            screen=_screen_from_mapping(screen),
            window=_window_from_mapping(screen),
        )
        _copy_screen_offsets(profile, fingerprint.screen)
        self._finalize_config(profile)
        return profile

    def compile_preset(self, preset: dict[str, Any], ff_version: str | None) -> CamoufoxProfile:
        _normalize_target_os(_preset_target_os(preset))

        navigator = preset.get("navigator", {})
        screen = preset.get("screen", {})

        navigator_profile = NavigatorProfile()
        screen_profile = ScreenProfile()
        window_profile = WindowProfile()
        profile = CamoufoxProfile(
            navigator=navigator_profile,
            screen=screen_profile,
            window=window_profile,
        )

        user_agent = navigator.get("userAgent")
        if isinstance(user_agent, str):
            patched_user_agent = _patch_firefox_version(user_agent, ff_version)
            navigator_profile.user_agent = patched_user_agent
            navigator_profile.app_version = _derive_app_version(patched_user_agent)

        platform_value = navigator.get("platform")
        if isinstance(platform_value, str):
            navigator_profile.platform = platform_value
        oscpu_value = navigator.get("oscpu")
        if isinstance(oscpu_value, str):
            navigator_profile.oscpu = oscpu_value
        if isinstance(preset.get("timezone"), str):
            profile.timezone = preset["timezone"]

        for source_key, target_attr in (
            ("width", "width"),
            ("height", "height"),
            ("availWidth", "avail_width"),
            ("availHeight", "avail_height"),
            ("availLeft", "avail_left"),
            ("availTop", "avail_top"),
            ("colorDepth", "color_depth"),
            ("pixelDepth", "pixel_depth"),
        ):
            value = screen.get(source_key)
            if isinstance(value, int):
                setattr(screen_profile, target_attr, max(value, 0))

        device_pixel_ratio = screen.get("devicePixelRatio")
        if isinstance(device_pixel_ratio, int | float):
            window_profile.device_pixel_ratio = float(device_pixel_ratio)

        self._finalize_config(profile)
        return profile

    def screen_from_browserforge(
        self,
        fingerprint: Fingerprint,
        config: CamoufoxProfile,
    ) -> _CompiledScreen:
        screen = asdict(fingerprint.screen)
        return _compiled_screen_from_profile(config, screen)

    def screen_from_preset(self, preset: dict[str, Any], config: CamoufoxProfile) -> _CompiledScreen:
        screen = preset.get("screen", {})
        return _compiled_screen_from_profile(config, screen)

    def build_context_options(
        self,
        config: CamoufoxProfile,
        screen: _CompiledScreen,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {}

        user_agent = config.navigator.user_agent if config.navigator else None
        if isinstance(user_agent, str):
            options["user_agent"] = user_agent

        if screen.width and screen.height:
            options["viewport"] = {
                "width": screen.width,
                "height": max(screen.height - 28, 600),
            }

        if screen.device_pixel_ratio:
            options["device_scale_factor"] = screen.device_pixel_ratio

        timezone = config.timezone
        if isinstance(timezone, str):
            options["timezone_id"] = timezone

        language = config.navigator.language if config.navigator else None
        if isinstance(language, str):
            options["locale"] = language

        return options

    def build_init_script(
        self,
        config: CamoufoxProfile,
        screen: _CompiledScreen,
        webrtc_ip: str | None,
    ) -> str:
        values = {
            "audioFingerprintSeed": config.audio.seed if config.audio else None,
            "canvasSeed": config.canvas.seed if config.canvas else None,
            "fontList": config.fonts.families if config.fonts else None,
            "fontSpacingSeed": config.fonts.spacing_seed if config.fonts else None,
            "navigatorOscpu": config.navigator.oscpu if config.navigator else None,
            "navigatorPlatform": config.navigator.platform if config.navigator else None,
            "navigatorUserAgent": config.navigator.user_agent if config.navigator else None,
            "screenColorDepth": screen.color_depth,
            "screenHeight": screen.height,
            "screenWidth": screen.width,
            "speechVoices": config.voices.items if config.voices else None,
            "timezone": config.timezone,
            "webrtcIP": webrtc_ip or "",
        }

        lines = ["(function() {", "  var w = window;"]
        for key, setter in (
            ("fontSpacingSeed", "setFontSpacingSeed"),
            ("audioFingerprintSeed", "setAudioFingerprintSeed"),
            ("canvasSeed", "setCanvasSeed"),
            ("navigatorPlatform", "setNavigatorPlatform"),
            ("navigatorOscpu", "setNavigatorOscpu"),
            ("navigatorUserAgent", "setNavigatorUserAgent"),
        ):
            value = values.get(key)
            if value is not None:
                lines.append(
                    f'  if (typeof w.{setter} === "function") w.{setter}({json.dumps(value)});'
                )

        if values["screenWidth"] and values["screenHeight"]:
            lines.append(
                "  if (typeof w.setScreenDimensions === \"function\") "
                f"w.setScreenDimensions({values['screenWidth']}, {values['screenHeight']});"
            )
            if values["screenColorDepth"] is not None:
                lines.append(
                    "  if (typeof w.setScreenColorDepth === \"function\") "
                    f"w.setScreenColorDepth({values['screenColorDepth']});"
                )

        if values["timezone"]:
            lines.append(
                "  if (typeof w.setTimezone === \"function\") "
                f"w.setTimezone({json.dumps(values['timezone'])});"
            )

        lines.append(
            "  if (typeof w.setWebRTCIPv4 === \"function\") "
            f"w.setWebRTCIPv4({json.dumps(values['webrtcIP'])});"
        )

        fonts = values["fontList"]
        if isinstance(fonts, list) and fonts:
            lines.append(
                "  if (typeof w.setFontList === \"function\") "
                f"w.setFontList({json.dumps(','.join(fonts))});"
            )

        voices = values["speechVoices"]
        if isinstance(voices, list) and voices:
            voice_names = [
                voice if isinstance(voice, str) else voice.name
                for voice in voices
            ]
            lines.append(
                "  if (typeof w.setSpeechVoices === \"function\") "
                f"w.setSpeechVoices({json.dumps(','.join(voice_names))});"
            )

        lines.append("})();")
        return "\n".join(lines)

    def _finalize_config(self, config: CamoufoxProfile) -> None:
        _ensure_oscpu(config)
        _snap_screen_to_common_macos_sizes(config)
        _merge_host_inventories(config, _MacOSHostProfile.current())
        _merge_seed_values(config)


def _apply_locale_override(config: CamoufoxProfile, locale: str) -> None:
    from .locales import normalize_locale

    parsed = normalize_locale(locale)
    config.locale = config.locale or LocaleProfile()
    config.navigator = config.navigator or NavigatorProfile()
    config.locale.language = parsed.language
    config.locale.region = parsed.region
    config.navigator.language = parsed.as_string
    if parsed.script:
        config.locale.script = parsed.script


def _normalize_target_os(value: Any | None) -> str:
    candidates: Sequence[str]
    if value is None:
        candidates = ("macos",)
    elif isinstance(value, str):
        candidates = (value,)
    else:
        candidates = tuple(value)

    for candidate in candidates:
        if candidate != "macos":
            raise NotImplementedError(
                f'Camoufox fingerprinting currently supports only the real macOS host. Refusing "{candidate}".'
            )

    if sys.platform != "darwin":
        raise NotImplementedError("Camoufox fingerprinting is currently implemented only for macOS hosts.")

    return "macos"


def _normalize_architecture(machine: str) -> str:
    return _HOST_ARCH_MAP.get(machine.lower(), machine.lower())


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _dedupe_list(items: Iterable[str]) -> list[str]:
    return list(_dedupe(items))


def _sample_extras(items: Sequence[str]) -> list[str]:
    if not items:
        return []

    count = randint(0, min(50, len(items)))  # nosec
    if count == 0:
        return []
    return sample(list(items), count)


def _as_optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _extract_device_pixel_ratio(screen: dict[str, Any]) -> float | None:
    for key in ("devicePixelRatio", "pixelRatio"):
        value = _as_optional_float(screen.get(key))
        if value is not None:
            return value
    return None


def _navigator_from_browserforge(navigator: dict[str, Any], ff_version: str | None) -> NavigatorProfile:
    profile = NavigatorProfile()
    user_agent = navigator.get("userAgent")
    if isinstance(user_agent, str):
        profile.user_agent = _patch_firefox_version(user_agent, ff_version)
        profile.app_version = _derive_app_version(profile.user_agent)

    for source_key, target_attr in (
        ("doNotTrack", "do_not_track"),
        ("appCodeName", "app_code_name"),
        ("appName", "app_name"),
        ("oscpu", "oscpu"),
        ("platform", "platform"),
        ("hardwareConcurrency", "hardware_concurrency"),
        ("product", "product"),
        ("maxTouchPoints", "max_touch_points"),
    ):
        value = navigator.get(source_key)
        if value is not None:
            setattr(profile, target_attr, value)

    extra = navigator.get("extraProperties", {})
    if isinstance(extra, dict) and isinstance(extra.get("globalPrivacyControl"), bool):
        profile.global_privacy_control = extra["globalPrivacyControl"]

    return profile


def _screen_from_mapping(screen: dict[str, Any]) -> ScreenProfile:
    profile = ScreenProfile()
    for source_key, target_attr in (
        ("availLeft", "avail_left"),
        ("availTop", "avail_top"),
        ("availWidth", "avail_width"),
        ("availHeight", "avail_height"),
        ("height", "height"),
        ("width", "width"),
        ("colorDepth", "color_depth"),
        ("pixelDepth", "pixel_depth"),
        ("pageXOffset", "page_x_offset"),
        ("pageYOffset", "page_y_offset"),
    ):
        value = screen.get(source_key)
        if isinstance(value, int) and target_attr in {
            "avail_left",
            "avail_top",
            "avail_width",
            "avail_height",
            "height",
            "width",
            "color_depth",
            "pixel_depth",
        }:
            value = max(value, 0)
        if value is not None:
            setattr(profile, target_attr, value)
    return profile


def _window_from_mapping(screen: dict[str, Any]) -> WindowProfile:
    profile = WindowProfile()
    for source_key, target_attr in (
        ("outerHeight", "outer_height"),
        ("outerWidth", "outer_width"),
        ("innerHeight", "inner_height"),
        ("innerWidth", "inner_width"),
        ("screenX", "screen_x"),
        ("screenY", "screen_y"),
    ):
        value = screen.get(source_key)
        if isinstance(value, int) and target_attr in {
            "outer_height",
            "outer_width",
            "inner_height",
            "inner_width",
        }:
            value = max(value, 0)
        if value is not None:
            setattr(profile, target_attr, value)

    profile.device_pixel_ratio = _extract_device_pixel_ratio(screen)
    return profile


def _compiled_screen_from_profile(config: CamoufoxProfile, source_screen: dict[str, Any]) -> _CompiledScreen:
    return _CompiledScreen(
        width=(config.screen.width if config.screen else None)
        or _as_optional_int(source_screen.get("width")),
        height=(config.screen.height if config.screen else None)
        or _as_optional_int(source_screen.get("height")),
        color_depth=(config.screen.color_depth if config.screen else None)
        or _as_optional_int(source_screen.get("colorDepth")),
        device_pixel_ratio=(config.window.device_pixel_ratio if config.window else None)
        or _extract_device_pixel_ratio(source_screen),
    )


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


def _merge_host_inventories(config: CamoufoxProfile, host: _MacOSHostProfile) -> None:
    config.fonts = config.fonts or FontsProfile()
    config.voices = config.voices or VoicesProfile()
    config.fonts.families = host.sample_fonts()
    sampled_voices: list[str | SpeechVoice] = list(host.sample_voices())
    config.voices.items = sampled_voices


def _copy_screen_offsets(config: CamoufoxProfile, screen: ScreenFingerprint) -> None:
    config.window = config.window or WindowProfile()
    if config.window.screen_x is None:
        config.window.screen_x = max(getattr(screen, "screenX", 0), 0)
    if config.window.screen_y is not None:
        return

    screen_x = getattr(screen, "screenX", 0)
    if screen_x in range(-50, 51):
        config.window.screen_y = max(screen_x, 0)
        return

    avail_height = getattr(screen, "availHeight", 0) - getattr(screen, "outerHeight", 0)
    if avail_height <= 0:
        config.window.screen_y = 0
    else:
        config.window.screen_y = randrange(0, avail_height)  # nosec


def _apply_window_override(fingerprint: Fingerprint, outer_width: int, outer_height: int) -> None:
    screen = fingerprint.screen
    screen.screenX += max((screen.width - outer_width) // 2, 0)
    if screen.innerWidth:
        screen.innerWidth = max(outer_width - screen.outerWidth + screen.innerWidth, 0)
    if screen.innerHeight:
        screen.innerHeight = max(outer_height - screen.outerHeight + screen.innerHeight, 0)
    screen.outerWidth = outer_width
    screen.outerHeight = outer_height
    if hasattr(screen, "screenY"):
        cast(Any, screen).screenY = max((screen.height - outer_height) // 2, 0)


def _ensure_oscpu(config: CamoufoxProfile) -> None:
    if not config.navigator:
        return
    if config.navigator.oscpu:
        return

    if config.navigator.platform == "MacIntel":
        config.navigator.oscpu = "Intel Mac OS X 10.15"


def _patch_firefox_version(value: str, ff_version: str | None) -> str:
    if not ff_version:
        return value

    value = re.sub(r"Firefox/\d+\.0", f"Firefox/{ff_version}.0", value)
    return re.sub(r"rv:\d+\.0", f"rv:{ff_version}.0", value)


def _derive_app_version(user_agent: str) -> str:
    match = re.search(r"\(([^)]+)\)", user_agent)
    if not match:
        return "5.0"
    return f"5.0 ({match.group(1)})"


def _snap_screen_to_common_macos_sizes(config: CamoufoxProfile) -> None:
    if not config.screen:
        return

    width = _as_optional_int(config.screen.width)
    height = _as_optional_int(config.screen.height)
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

    outer_width = _as_optional_int(config.window.outer_width)
    inner_width = _as_optional_int(config.window.inner_width)
    if outer_width is not None:
        width_delta = outer_width - inner_width if inner_width is not None else 0
        config.window.outer_width = min(outer_width, snapped_width)
        if inner_width is not None:
            config.window.inner_width = max(config.window.outer_width - width_delta, 0)

    outer_height = _as_optional_int(config.window.outer_height)
    inner_height = _as_optional_int(config.window.inner_height)
    if outer_height is not None:
        height_delta = outer_height - inner_height if inner_height is not None else 0
        config.window.outer_height = min(outer_height, snapped_height)
        if inner_height is not None:
            config.window.inner_height = max(config.window.outer_height - height_delta, 0)


def _probe_gpu_family() -> tuple[str | None, str | None]:
    data = _run_host_json("system_profiler", "SPDisplaysDataType", "-json")
    for entry in data.get("SPDisplaysDataType", []):
        renderer = entry.get("sppci_model") or entry.get("_name") or ""
        vendor = _normalize_gpu_vendor(f"{entry.get('spdisplays_vendor', '')} {renderer}")
        family = _normalize_gpu_family(renderer)
        return vendor, family
    return None, None


def _probe_fonts() -> tuple[_FontRecord, ...]:
    data = _run_host_json("system_profiler", "SPFontsDataType", "-json")
    records: list[_FontRecord] = []
    seen: set[str] = set()

    for entry in data.get("SPFontsDataType", []):
        if entry.get("enabled") != "yes":
            continue

        font_path = entry.get("path", "")
        for face in entry.get("typefaces", []):
            if face.get("enabled") != "yes" or face.get("valid") == "no":
                continue
            family = face.get("family")
            if not isinstance(family, str) or family in seen:
                continue
            seen.add(family)
            records.append(_FontRecord(family=family, path=font_path))

    return tuple(records)


def _probe_voices() -> tuple[str, ...]:
    output = _run_host_text("say", "-v", "?")
    names: list[str] = []

    for line in output.splitlines():
        match = re.match(r"^(?P<name>.+?)\s{2,}[A-Za-z_]+\s+#", line.rstrip())
        if match:
            names.append(match.group("name").strip())

    return _dedupe(names)


def _run_host_text(*args: str) -> str:
    result = subprocess.run(
        args,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _run_host_json(*args: str) -> dict[str, Any]:
    return json.loads(_run_host_text(*args))


def _is_system_font(font_path: str) -> bool:
    return any(font_path.startswith(prefix) for prefix in _SYSTEM_FONT_PREFIXES)


def _is_bundled_voice(name: str) -> bool:
    lowered = name.lower()
    return "enhanced" not in lowered and "premium" not in lowered and "(" not in lowered


def _preset_target_os(preset: dict[str, Any]) -> str:
    user_agent = preset.get("navigator", {}).get("userAgent", "")
    if isinstance(user_agent, str) and "Macintosh" in user_agent:
        return "macos"
    return "macos"


def _normalize_gpu_vendor(text: str) -> str | None:
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


def _normalize_gpu_family(text: str) -> str | None:
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
    return _normalize_gpu_vendor(text)
