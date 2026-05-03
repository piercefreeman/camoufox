from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from random import randrange
from typing import Any, ClassVar, cast

from browserforge.fingerprints import (
    Fingerprint,
    FingerprintGenerator,
    ScreenFingerprint,
)

from ._generated_profile import (
    CamoufoxProfile,
    LocaleProfile,
    NavigatorProfile,
    ScreenProfile,
    WindowProfile,
)
from .fingerprinting.common import HostTargetOS, LINUX, MACOS, TargetOS, WINDOWS
from .fingerprinting import (
    HostFingerprintAdapter,
    current_host_target_os,
    get_host_adapter,
    normalize_target_os,
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

    When `preset` is omitted, BrowserForge generates the Firefox skeleton for
    the current host OS and Camoufox normalizes it into a smaller
    host-compatible config.
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
    _debug_log(debug, "Preparing fingerprinted browser context.")

    if fingerprint is not None and preset is not None:
        raise ValueError("Pass either `fingerprint` or `preset`, not both.")

    if fingerprint is not None:
        compiler = _FirefoxFingerprintCompiler.current(_browserforge_target_os(fingerprint))
        _debug_log(debug, "Reusing caller-supplied BrowserForge fingerprint.")
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    elif preset is None:
        compiler = _FirefoxFingerprintCompiler.current(os)
        _debug_log(debug, "Generating BrowserForge Firefox skeleton.")
        fingerprint = generate_fingerprint(os=os, debug=debug)
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    else:
        compiler = _FirefoxFingerprintCompiler.current(_preset_target_os(preset))
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
    Generate a BrowserForge Firefox fingerprint constrained to the real host OS.

    This is the lowest-level public constructor for the active fingerprint flow.
    The generated object still looks like BrowserForge output; call
    `from_browserforge()` to compile it into a Camoufox config map.
    """
    requested_os = config.get("os") or current_host_target_os()
    _debug_log(debug, f"Requesting BrowserForge fingerprint for os={requested_os}.")
    fingerprint = _FirefoxFingerprintCompiler.current(requested_os).generate(window=window, **config)
    _GENERATED_FINGERPRINT_IDS.add(id(fingerprint))
    _debug_log(debug, "BrowserForge fingerprint generated successfully.")
    return fingerprint


def from_browserforge(fingerprint: Fingerprint, ff_version: str | None = None) -> CamoufoxProfile:
    """
    Compile a BrowserForge fingerprint into a host-compatible `CamoufoxProfile`.

    Only a small set of values are carried forward: Firefox navigator fields,
    screen/window geometry, timezone/locale, noise seeds, and the sampled font
    and voice inventories that are actually present on the local host.
    """
    return _FirefoxFingerprintCompiler.current(_browserforge_target_os(fingerprint)).compile_browserforge(
        fingerprint,
        ff_version,
    )


def from_preset(preset: dict[str, Any], ff_version: str | None = None) -> CamoufoxProfile:
    """
    Compile an explicit caller-supplied preset into a host-compatible `CamoufoxProfile`.

    This path exists for callers that already have a preset dictionary and want
    Camoufox to normalize it the same way as BrowserForge output. Camoufox no
    longer ships a bundled preset corpus.
    """
    return _FirefoxFingerprintCompiler.current(_preset_target_os(preset)).compile_preset(
        preset,
        ff_version,
    )


def is_generated_fingerprint(fingerprint: Fingerprint) -> bool:
    """
    Return whether a fingerprint was produced by Camoufox's BrowserForge helper.
    """
    return id(fingerprint) in _GENERATED_FINGERPRINT_IDS


def _debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[camoufox:fingerprint] {message}")


@dataclass(frozen=True)
class _CompiledScreen:
    width: int | None
    height: int | None
    color_depth: int | None
    device_pixel_ratio: float | None = None


@dataclass(frozen=True)
class _FirefoxFingerprintCompiler:
    target_os: HostTargetOS
    host: HostFingerprintAdapter
    generator: FingerprintGenerator

    _cached: ClassVar[dict[HostTargetOS, "_FirefoxFingerprintCompiler"]] = {}

    @classmethod
    def current(cls, target_os: Any | None = None) -> _FirefoxFingerprintCompiler:
        normalized = normalize_target_os(target_os)
        cached = cls._cached.get(normalized)
        if cached is None:
            cached = cls(
                target_os=normalized,
                host=get_host_adapter(normalized),
                generator=FingerprintGenerator(browser="firefox", os=(normalized,)),
            )
            cls._cached[normalized] = cached
        return cached

    def generate(self, window: tuple[int, int] | None = None, **config: Any) -> Fingerprint:
        config["os"] = normalize_target_os(config.get("os") or self.target_os)
        fingerprint = self.generator.generate(**config)
        if window:
            _apply_window_override(fingerprint, *window)
        return fingerprint

    def compile_browserforge(
        self,
        fingerprint: Fingerprint,
        ff_version: str | None,
    ) -> CamoufoxProfile:
        normalize_target_os(_browserforge_target_os(fingerprint))
        source = asdict(fingerprint)
        navigator = source.get("navigator", {})
        screen = asdict(fingerprint.screen)

        profile = CamoufoxProfile(
            navigator=_navigator_from_browserforge(navigator, ff_version),
            screen=_screen_from_mapping(screen),
            window=_window_from_mapping(screen),
        )
        _copy_screen_offsets(profile, fingerprint.screen)
        self.host.finalize_config(profile)
        return profile

    def compile_preset(self, preset: dict[str, Any], ff_version: str | None) -> CamoufoxProfile:
        normalize_target_os(_preset_target_os(preset))

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

        self.host.finalize_config(profile)
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
            "hardwareConcurrency": (
                config.navigator.hardware_concurrency if config.navigator else None
            ),
            "navigatorOscpu": config.navigator.oscpu if config.navigator else None,
            "navigatorPlatform": config.navigator.platform if config.navigator else None,
            "navigatorUserAgent": config.navigator.user_agent if config.navigator else None,
            "screenColorDepth": screen.color_depth,
            "screenHeight": screen.height,
            "screenWidth": screen.width,
            "speechVoices": config.voices.items if config.voices else None,
            "timezone": config.timezone,
            "webrtcIP": webrtc_ip or "",
            "webglRenderer": config.web_gl.renderer if config.web_gl else None,
            "webglVendor": config.web_gl.vendor if config.web_gl else None,
        }

        lines = ["(function() {", "  var w = window;"]
        for key, setter in (
            ("fontSpacingSeed", "setFontSpacingSeed"),
            ("audioFingerprintSeed", "setAudioFingerprintSeed"),
            ("canvasSeed", "setCanvasSeed"),
            ("navigatorPlatform", "setNavigatorPlatform"),
            ("navigatorOscpu", "setNavigatorOscpu"),
            ("hardwareConcurrency", "setNavigatorHardwareConcurrency"),
            ("navigatorUserAgent", "setNavigatorUserAgent"),
            ("webglVendor", "setWebGLVendor"),
            ("webglRenderer", "setWebGLRenderer"),
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

        for setter in (
            "setFontSpacingSeed",
            "setAudioFingerprintSeed",
            "setCanvasSeed",
            "setTimezone",
            "setScreenDimensions",
            "setScreenColorDepth",
            "setNavigatorPlatform",
            "setNavigatorOscpu",
            "setNavigatorHardwareConcurrency",
            "setNavigatorUserAgent",
            "setWebGLVendor",
            "setWebGLRenderer",
            "setFontList",
            "setSpeechVoices",
            "setWebRTCIPv4",
        ):
            lines.append(
                f'  try {{ w.{setter} = undefined; delete w.{setter}; }} catch (e) {{}}'
            )

        lines.append("})();")
        return "\n".join(lines)


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

def _preset_target_os(preset: dict[str, Any]) -> TargetOS:
    navigator = preset.get("navigator", {})
    return _infer_target_os(
        navigator.get("platform"),
        navigator.get("oscpu"),
        navigator.get("userAgent"),
    )


def _browserforge_target_os(fingerprint: Fingerprint) -> TargetOS:
    navigator = getattr(fingerprint, "navigator", None)
    return _infer_target_os(
        getattr(navigator, "platform", None),
        getattr(navigator, "oscpu", None),
        getattr(navigator, "userAgent", None),
    )


def _infer_target_os(*values: Any) -> TargetOS:
    for value in values:
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if "linux" in lowered or "x11" in lowered:
            return LINUX
        if "mac" in lowered or "darwin" in lowered:
            return MACOS
        if "windows" in lowered or lowered.startswith("win"):
            return WINDOWS
    return current_host_target_os()
