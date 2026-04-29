from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from random import randint, randrange, sample
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Sequence, Tuple

from browserforge.fingerprints import Fingerprint, FingerprintGenerator, ScreenFingerprint

from camoufox.pkgman import load_yaml

_GENERATED_FINGERPRINT_IDS: set[int] = set()


def generate_context_fingerprint(
    fingerprint: Optional[Fingerprint] = None,
    preset: Optional[Dict[str, Any]] = None,
    os: Optional[str] = None,
    ff_version: Optional[str] = None,
    webrtc_ip: Optional[str] = None,
    timezone: Optional[str] = None,
    locale: Optional[str] = None,
    debug: bool = False,
) -> Dict[str, Any]:
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
    - `config`: the final CAMOU_CONFIG-style values
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
        config["timezone"] = timezone
    if locale:
        _apply_locale_override(config, locale)

    context_options = compiler.build_context_options(config, screen)
    _debug_log(
        debug,
        "Fingerprint ready: "
        f"screen={screen.width}x{screen.height}, "
        f"fonts={len(config.get('fonts', []))}, "
        f"voices={len(config.get('voices', []))}, "
        f"timezone={config.get('timezone', 'system')}",
    )
    _debug_log(debug, f"Context options ready: {context_options}")

    return {
        "init_script": compiler.build_init_script(config, screen, webrtc_ip),
        "context_options": context_options,
        "config": config,
        "preset": preset,
    }


def generate_fingerprint(
    window: Optional[Tuple[int, int]] = None,
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


def from_browserforge(fingerprint: Fingerprint, ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Compile a BrowserForge fingerprint into a host-compatible `CAMOU_CONFIG`.

    Only a small set of values are carried forward: Firefox navigator fields,
    screen/window geometry, timezone/locale, noise seeds, and the sampled font
    and voice inventories that are actually present on the local macOS host.
    """
    return _FirefoxFingerprintCompiler.current().compile_browserforge(fingerprint, ff_version)


def from_preset(preset: Dict[str, Any], ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Compile an explicit caller-supplied preset into a host-compatible `CAMOU_CONFIG`.

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


_BROWSERFORGE_MAPPING = load_yaml("browserforge.yml")

_PUBLIC_CONFIG_KEYS = frozenset(
    {
        "audio:seed",
        "canvas:seed",
        "fonts",
        "fonts:spacing_seed",
        "locale:language",
        "locale:region",
        "locale:script",
        "navigator.appVersion",
        "navigator.language",
        "navigator.oscpu",
        "navigator.platform",
        "navigator.userAgent",
        "screen.availHeight",
        "screen.availLeft",
        "screen.availTop",
        "screen.availWidth",
        "screen.colorDepth",
        "screen.height",
        "screen.pixelDepth",
        "screen.width",
        "timezone",
        "voices",
        "window.devicePixelRatio",
        "window.innerHeight",
        "window.innerWidth",
        "window.outerHeight",
        "window.outerWidth",
        "window.screenX",
        "window.screenY",
    }
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

_SYSTEM_FONT_PREFIXES = (
    "/System/Library/Fonts",
    "/System/Library/AssetsV2",
    "/Library/Apple/System/Library/Fonts",
)

_COMMON_MACOS_SCREEN_SIZES: Tuple[Tuple[int, int], ...] = (
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
    width: Optional[int]
    height: Optional[int]
    color_depth: Optional[int]
    device_pixel_ratio: Optional[float] = None


@dataclass(frozen=True)
class _FontRecord:
    family: str
    path: str


@dataclass(frozen=True)
class _MacOSHostProfile:
    architecture: str
    gpu_vendor: Optional[str]
    gpu_family: Optional[str]
    bundled_fonts: Tuple[str, ...]
    extra_fonts: Tuple[str, ...]
    bundled_voices: Tuple[str, ...]
    extra_voices: Tuple[str, ...]

    _cached: ClassVar[Optional["_MacOSHostProfile"]] = None

    @classmethod
    def current(cls) -> "_MacOSHostProfile":
        if cls._cached is None:
            cls._cached = cls._probe()
        return cls._cached

    @classmethod
    def _probe(cls) -> "_MacOSHostProfile":
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

    def sample_fonts(self) -> List[str]:
        fonts = list(self.bundled_fonts)
        fonts.extend(_sample_extras(self.extra_fonts))
        for marker in _MACOS_MARKER_FONTS:
            if marker in self.bundled_fonts and marker not in fonts:
                fonts.append(marker)
        return _dedupe_list(fonts)

    def sample_voices(self) -> List[str]:
        voices = list(self.bundled_voices)
        voices.extend(_sample_extras(self.extra_voices))
        return _dedupe_list(voices)


@dataclass(frozen=True)
class _FirefoxFingerprintCompiler:
    generator: FingerprintGenerator

    _cached: ClassVar[Optional["_FirefoxFingerprintCompiler"]] = None

    @classmethod
    def current(cls) -> "_FirefoxFingerprintCompiler":
        if cls._cached is None:
            cls._cached = cls(generator=FingerprintGenerator(browser="firefox", os=("macos",)))
        return cls._cached

    def generate(self, window: Optional[Tuple[int, int]] = None, **config: Any) -> Fingerprint:
        config["os"] = _normalize_target_os(config.get("os"))
        fingerprint = self.generator.generate(**config)
        if window:
            _apply_window_override(fingerprint, *window)
        return fingerprint

    def compile_browserforge(
        self,
        fingerprint: Fingerprint,
        ff_version: Optional[str],
    ) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        self._cast_to_config(config, _BROWSERFORGE_MAPPING, asdict(fingerprint), ff_version)
        _copy_screen_offsets(config, fingerprint.screen)

        user_agent = config.get("navigator.userAgent")
        if isinstance(user_agent, str):
            config["navigator.appVersion"] = _derive_app_version(user_agent)

        self._finalize_config(config)
        return _filter_public_config(config)

    def compile_preset(self, preset: Dict[str, Any], ff_version: Optional[str]) -> Dict[str, Any]:
        _normalize_target_os(_preset_target_os(preset))

        config: Dict[str, Any] = {}
        navigator = preset.get("navigator", {})
        screen = preset.get("screen", {})

        user_agent = navigator.get("userAgent")
        if isinstance(user_agent, str):
            config["navigator.userAgent"] = _patch_firefox_version(user_agent, ff_version)
            config["navigator.appVersion"] = _derive_app_version(config["navigator.userAgent"])

        if isinstance(navigator.get("platform"), str):
            config["navigator.platform"] = navigator["platform"]
        if isinstance(navigator.get("oscpu"), str):
            config["navigator.oscpu"] = navigator["oscpu"]
        if isinstance(preset.get("timezone"), str):
            config["timezone"] = preset["timezone"]

        for source_key, target_key in (
            ("width", "screen.width"),
            ("height", "screen.height"),
            ("availWidth", "screen.availWidth"),
            ("availHeight", "screen.availHeight"),
            ("availLeft", "screen.availLeft"),
            ("availTop", "screen.availTop"),
            ("colorDepth", "screen.colorDepth"),
            ("pixelDepth", "screen.pixelDepth"),
        ):
            value = screen.get(source_key)
            if isinstance(value, int):
                config[target_key] = max(value, 0)

        device_pixel_ratio = screen.get("devicePixelRatio")
        if isinstance(device_pixel_ratio, (int, float)):
            config["window.devicePixelRatio"] = float(device_pixel_ratio)

        self._finalize_config(config)
        return _filter_public_config(config)

    def screen_from_browserforge(
        self,
        fingerprint: Fingerprint,
        config: Dict[str, Any],
    ) -> _CompiledScreen:
        screen = asdict(fingerprint.screen)
        return _CompiledScreen(
            width=_as_optional_int(config.get("screen.width")) or _as_optional_int(screen.get("width")),
            height=_as_optional_int(config.get("screen.height")) or _as_optional_int(screen.get("height")),
            color_depth=_as_optional_int(config.get("screen.colorDepth"))
            or _as_optional_int(screen.get("colorDepth")),
            device_pixel_ratio=_extract_device_pixel_ratio(screen),
        )

    def screen_from_preset(self, preset: Dict[str, Any], config: Dict[str, Any]) -> _CompiledScreen:
        screen = preset.get("screen", {})
        return _CompiledScreen(
            width=_as_optional_int(config.get("screen.width")) or _as_optional_int(screen.get("width")),
            height=_as_optional_int(config.get("screen.height")) or _as_optional_int(screen.get("height")),
            color_depth=_as_optional_int(config.get("screen.colorDepth"))
            or _as_optional_int(screen.get("colorDepth")),
            device_pixel_ratio=_as_optional_float(config.get("window.devicePixelRatio"))
            or _as_optional_float(screen.get("devicePixelRatio")),
        )

    def build_context_options(
        self,
        config: Dict[str, Any],
        screen: _CompiledScreen,
    ) -> Dict[str, Any]:
        options: Dict[str, Any] = {}

        user_agent = config.get("navigator.userAgent")
        if isinstance(user_agent, str):
            options["user_agent"] = user_agent

        if screen.width and screen.height:
            options["viewport"] = {
                "width": screen.width,
                "height": max(screen.height - 28, 600),
            }

        if screen.device_pixel_ratio:
            options["device_scale_factor"] = screen.device_pixel_ratio

        timezone = config.get("timezone")
        if isinstance(timezone, str):
            options["timezone_id"] = timezone

        language = config.get("navigator.language")
        if isinstance(language, str):
            options["locale"] = language

        return options

    def build_init_script(
        self,
        config: Dict[str, Any],
        screen: _CompiledScreen,
        webrtc_ip: Optional[str],
    ) -> str:
        values = {
            "audioFingerprintSeed": config.get("audio:seed"),
            "canvasSeed": config.get("canvas:seed"),
            "fontList": config.get("fonts"),
            "fontSpacingSeed": config.get("fonts:spacing_seed"),
            "navigatorOscpu": config.get("navigator.oscpu"),
            "navigatorPlatform": config.get("navigator.platform"),
            "navigatorUserAgent": config.get("navigator.userAgent"),
            "screenColorDepth": screen.color_depth,
            "screenHeight": screen.height,
            "screenWidth": screen.width,
            "speechVoices": config.get("voices"),
            "timezone": config.get("timezone"),
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
            lines.append(
                "  if (typeof w.setSpeechVoices === \"function\") "
                f"w.setSpeechVoices({json.dumps(','.join(voices))});"
            )

        lines.append("})();")
        return "\n".join(lines)

    def _finalize_config(self, config: Dict[str, Any]) -> None:
        _ensure_oscpu(config)
        _snap_screen_to_common_macos_sizes(config)
        _merge_host_inventories(config, _MacOSHostProfile.current())
        _merge_seed_values(config)

    def _cast_to_config(
        self,
        target: Dict[str, Any],
        schema: Dict[str, Any],
        source: Dict[str, Any],
        ff_version: Optional[str],
    ) -> None:
        for key, value in source.items():
            if value is None:
                continue

            mapped = schema.get(key)
            if mapped is None:
                continue

            if isinstance(value, dict):
                self._cast_to_config(target, mapped, value, ff_version)
                continue

            if isinstance(value, str) and ff_version:
                value = _patch_firefox_version(value, ff_version)
            if isinstance(value, int) and mapped.startswith("screen."):
                value = max(value, 0)

            target[mapped] = value


def _apply_locale_override(config: Dict[str, Any], locale: str) -> None:
    from .locales import normalize_locale

    parsed = normalize_locale(locale)
    config["locale:language"] = parsed.language
    config["locale:region"] = parsed.region
    config["navigator.language"] = parsed.as_string
    if parsed.script:
        config["locale:script"] = parsed.script


def _normalize_target_os(value: Optional[Any]) -> str:
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


def _dedupe(items: Iterable[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _dedupe_list(items: Iterable[str]) -> List[str]:
    return list(_dedupe(items))


def _sample_extras(items: Sequence[str]) -> List[str]:
    if not items:
        return []

    count = randint(0, min(50, len(items)))  # nosec
    if count == 0:
        return []
    return sample(list(items), count)


def _as_optional_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) else None


def _as_optional_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_device_pixel_ratio(screen: Dict[str, Any]) -> Optional[float]:
    for key in ("devicePixelRatio", "pixelRatio"):
        value = _as_optional_float(screen.get(key))
        if value is not None:
            return value
    return None


def _merge_seed_values(config: Dict[str, Any]) -> None:
    config.setdefault("fonts:spacing_seed", randint(1, 4_294_967_295))  # nosec
    config.setdefault("audio:seed", randint(1, 4_294_967_295))  # nosec
    config.setdefault("canvas:seed", randint(1, 4_294_967_295))  # nosec


def _merge_host_inventories(config: Dict[str, Any], host: _MacOSHostProfile) -> None:
    config["fonts"] = host.sample_fonts()
    config["voices"] = host.sample_voices()


def _filter_public_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in config.items() if key in _PUBLIC_CONFIG_KEYS}


def _copy_screen_offsets(config: Dict[str, Any], screen: ScreenFingerprint) -> None:
    if "window.screenX" not in config:
        config["window.screenX"] = max(getattr(screen, "screenX", 0), 0)
    if "window.screenY" in config:
        return

    screen_x = getattr(screen, "screenX", 0)
    if screen_x in range(-50, 51):
        config["window.screenY"] = max(screen_x, 0)
        return

    avail_height = getattr(screen, "availHeight", 0) - getattr(screen, "outerHeight", 0)
    if avail_height <= 0:
        config["window.screenY"] = 0
    else:
        config["window.screenY"] = randrange(0, avail_height)  # nosec


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
        screen.screenY = max((screen.height - outer_height) // 2, 0)


def _ensure_oscpu(config: Dict[str, Any]) -> None:
    if config.get("navigator.oscpu"):
        return

    platform_name = config.get("navigator.platform")
    if platform_name == "MacIntel":
        config["navigator.oscpu"] = "Intel Mac OS X 10.15"


def _patch_firefox_version(value: str, ff_version: Optional[str]) -> str:
    if not ff_version:
        return value

    value = re.sub(r"Firefox/\d+\.0", f"Firefox/{ff_version}.0", value)
    value = re.sub(r"rv:\d+\.0", f"rv:{ff_version}.0", value)
    return value


def _derive_app_version(user_agent: str) -> str:
    match = re.search(r"\(([^)]+)\)", user_agent)
    if not match:
        return "5.0"
    return f"5.0 ({match.group(1)})"


def _snap_screen_to_common_macos_sizes(config: Dict[str, Any]) -> None:
    width = _as_optional_int(config.get("screen.width"))
    height = _as_optional_int(config.get("screen.height"))
    if width is None or height is None:
        return

    snapped_width, snapped_height = min(
        _COMMON_MACOS_SCREEN_SIZES,
        key=lambda size: abs(size[0] - width) + abs(size[1] - height),
    )

    config["screen.width"] = snapped_width
    config["screen.height"] = snapped_height
    config["screen.availWidth"] = snapped_width
    config["screen.availHeight"] = snapped_height

    outer_width = _as_optional_int(config.get("window.outerWidth"))
    inner_width = _as_optional_int(config.get("window.innerWidth"))
    if outer_width is not None:
        width_delta = outer_width - inner_width if inner_width is not None else 0
        config["window.outerWidth"] = min(outer_width, snapped_width)
        if inner_width is not None:
            config["window.innerWidth"] = max(config["window.outerWidth"] - width_delta, 0)

    outer_height = _as_optional_int(config.get("window.outerHeight"))
    inner_height = _as_optional_int(config.get("window.innerHeight"))
    if outer_height is not None:
        height_delta = outer_height - inner_height if inner_height is not None else 0
        config["window.outerHeight"] = min(outer_height, snapped_height)
        if inner_height is not None:
            config["window.innerHeight"] = max(config["window.outerHeight"] - height_delta, 0)


def _probe_gpu_family() -> Tuple[Optional[str], Optional[str]]:
    data = _run_host_json("system_profiler", "SPDisplaysDataType", "-json")
    for entry in data.get("SPDisplaysDataType", []):
        renderer = entry.get("sppci_model") or entry.get("_name") or ""
        vendor = _normalize_gpu_vendor(f"{entry.get('spdisplays_vendor', '')} {renderer}")
        family = _normalize_gpu_family(renderer)
        return vendor, family
    return None, None


def _probe_fonts() -> Tuple[_FontRecord, ...]:
    data = _run_host_json("system_profiler", "SPFontsDataType", "-json")
    records: List[_FontRecord] = []
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


def _probe_voices() -> Tuple[str, ...]:
    output = _run_host_text("say", "-v", "?")
    names: List[str] = []

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


def _run_host_json(*args: str) -> Dict[str, Any]:
    return json.loads(_run_host_text(*args))


def _is_system_font(font_path: str) -> bool:
    return any(font_path.startswith(prefix) for prefix in _SYSTEM_FONT_PREFIXES)


def _is_bundled_voice(name: str) -> bool:
    lowered = name.lower()
    return "enhanced" not in lowered and "premium" not in lowered and "(" not in lowered


def _preset_target_os(preset: Dict[str, Any]) -> str:
    user_agent = preset.get("navigator", {}).get("userAgent", "")
    if isinstance(user_agent, str) and "Macintosh" in user_agent:
        return "macos"
    return "macos"


def _normalize_gpu_vendor(text: str) -> Optional[str]:
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


def _normalize_gpu_family(text: str) -> Optional[str]:
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
