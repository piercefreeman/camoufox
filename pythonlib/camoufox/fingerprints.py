from __future__ import annotations

from typing import Any

from browserforge.fingerprints import Fingerprint

from ._generated_profile import CamoufoxProfile, LocaleProfile, NavigatorProfile
from .fingerprinting import current_host_target_os
from .fingerprinting.compiler import FirefoxFingerprintCompiler
from .fingerprinting.compiler import browserforge_target_os as _browserforge_target_os
from .fingerprinting.compiler import preset_target_os as _preset_target_os

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
        compiler = FirefoxFingerprintCompiler.current(_browserforge_target_os(fingerprint))
        _debug_log(debug, "Reusing caller-supplied BrowserForge fingerprint.")
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    elif preset is None:
        compiler = FirefoxFingerprintCompiler.current(os)
        _debug_log(debug, "Generating BrowserForge Firefox skeleton.")
        fingerprint = generate_fingerprint(os=os, debug=debug)
        config = compiler.compile_browserforge(fingerprint, ff_version)
        screen = compiler.screen_from_browserforge(fingerprint, config)
    else:
        compiler = FirefoxFingerprintCompiler.current(_preset_target_os(preset))
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
    fingerprint = FirefoxFingerprintCompiler.current(requested_os).generate(
        window=window,
        **config,
    )
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
    return FirefoxFingerprintCompiler.current(
        _browserforge_target_os(fingerprint)
    ).compile_browserforge(fingerprint, ff_version)


def from_preset(preset: dict[str, Any], ff_version: str | None = None) -> CamoufoxProfile:
    """
    Compile an explicit caller-supplied preset into a host-compatible `CamoufoxProfile`.

    This path exists for callers that already have a preset dictionary and want
    Camoufox to normalize it the same way as BrowserForge output. Camoufox no
    longer ships a bundled preset corpus.
    """
    return FirefoxFingerprintCompiler.current(_preset_target_os(preset)).compile_preset(
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


def _apply_locale_override(config: CamoufoxProfile, locale: str) -> None:
    from .geo.locales import normalize_locale

    parsed = normalize_locale(locale)
    config.locale = config.locale or LocaleProfile()
    config.navigator = config.navigator or NavigatorProfile()
    config.locale.language = parsed.language
    config.locale.region = parsed.region
    config.navigator.language = parsed.as_string
    if parsed.script:
        config.locale.script = parsed.script
