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

from .._generated_profile import (
    CamoufoxProfile,
    NavigatorProfile,
    ScreenProfile,
    WindowProfile,
)
from .common import LINUX, MACOS, WINDOWS, HostTargetOS, TargetOS
from .hosts import (
    HostFingerprintAdapter,
    current_host_target_os,
    get_host_adapter,
    normalize_target_os,
)


@dataclass(frozen=True)
class CompiledScreen:
    width: int | None
    height: int | None
    color_depth: int | None
    device_pixel_ratio: float | None = None


@dataclass(frozen=True)
class FirefoxFingerprintCompiler:
    """
    Compile Firefox-oriented fingerprint sources into the runtime payload Camoufox uses.

    This class owns the translation boundary between upstream fingerprint inputs and
    Camoufox's internal browser profile model. It accepts either BrowserForge
    fingerprints or caller-supplied preset dictionaries, extracts the subset of
    Firefox-relevant fields we actually honor, and produces three coupled outputs:
    a normalized `CamoufoxProfile`, Playwright context options derived from that
    profile, and the per-context init script values that must stay in sync with it.

    It does not own host discovery or OS-specific realism policy. Those concerns
    stay in `HostFingerprintAdapter` implementations, which finalize the compiled
    profile after the raw field mapping step. Public orchestration such as
    argument validation and explicit locale/timezone overrides stays in
    `camoufox.fingerprints`.

    Instances are cached per host target OS because both the BrowserForge
    generator configuration and the host adapter are OS-bound.
    """

    target_os: HostTargetOS
    host: HostFingerprintAdapter
    generator: FingerprintGenerator

    _cached: ClassVar[dict[HostTargetOS, FirefoxFingerprintCompiler]] = {}

    @classmethod
    def current(cls, target_os: Any | None = None) -> FirefoxFingerprintCompiler:
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
        normalize_target_os(browserforge_target_os(fingerprint))
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
        normalize_target_os(preset_target_os(preset))

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
    ) -> CompiledScreen:
        screen = asdict(fingerprint.screen)
        return _compiled_screen_from_profile(config, screen)

    def screen_from_preset(
        self,
        preset: dict[str, Any],
        config: CamoufoxProfile,
    ) -> CompiledScreen:
        screen = preset.get("screen", {})
        return _compiled_screen_from_profile(config, screen)

    def build_context_options(
        self,
        config: CamoufoxProfile,
        screen: CompiledScreen,
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
        screen: CompiledScreen,
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
            voice_names = [voice if isinstance(voice, str) else voice.name for voice in voices]
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
            lines.append(f"  try {{ w.{setter} = undefined; delete w.{setter}; }} catch (e) {{}}")

        lines.append("})();")
        return "\n".join(lines)


def preset_target_os(preset: dict[str, Any]) -> TargetOS:
    navigator = preset.get("navigator", {})
    return infer_target_os(
        navigator.get("platform"),
        navigator.get("oscpu"),
        navigator.get("userAgent"),
    )


def browserforge_target_os(fingerprint: Fingerprint) -> TargetOS:
    navigator = getattr(fingerprint, "navigator", None)
    return infer_target_os(
        getattr(navigator, "platform", None),
        getattr(navigator, "oscpu", None),
        getattr(navigator, "userAgent", None),
    )


def infer_target_os(*values: Any) -> TargetOS:
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


def _navigator_from_browserforge(
    navigator: dict[str, Any],
    ff_version: str | None,
) -> NavigatorProfile:
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


def _compiled_screen_from_profile(
    config: CamoufoxProfile,
    source_screen: dict[str, Any],
) -> CompiledScreen:
    return CompiledScreen(
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
