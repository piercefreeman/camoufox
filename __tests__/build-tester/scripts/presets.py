"""
Fingerprint preset generation, injection, and profile config conversion.
"""

import json
import re
import sys
from typing import Any

from constants import TEST_TIMEZONES, WEBRTC_TEST_IP


# ─── Preset Generation ────────────────────────────────────────────────────────

def _config_to_dict(config: Any) -> dict[str, Any]:
    if hasattr(config, "model_dump"):
        return config.model_dump(by_alias=True, exclude_none=True, mode="json")
    if isinstance(config, dict):
        return config
    raise TypeError(f"Unsupported config type: {type(config)!r}")


def _voice_names(values: list[Any] | None) -> list[str]:
    names: list[str] = []
    for value in values or []:
        if isinstance(value, str):
            names.append(value)
        elif hasattr(value, "name") and isinstance(value.name, str):
            names.append(value.name)
    return names


def convert_preset(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Convert generate_context_fingerprint() output into the build-tester shape.

    The current Camoufox helper returns:
    - `config` as a typed CamoufoxProfile model
    - `preset` as `None` when the identity was generated from BrowserForge
    Older build-tester code assumed both were plain dicts.
    """
    config = ctx["config"]
    config_dict = _config_to_dict(config)
    navigator = getattr(config, "navigator", None)
    screen = getattr(config, "screen", None)
    fonts = getattr(config, "fonts", None)
    audio = getattr(config, "audio", None)
    voices = getattr(config, "voices", None)

    return {
        "initScript": ctx["init_script"],
        "contextOptions": {
            "userAgent": ctx["context_options"].get("user_agent"),
            "viewport": ctx["context_options"].get("viewport"),
            "deviceScaleFactor": ctx["context_options"].get("device_scale_factor"),
            "locale": ctx["context_options"].get("locale"),
            "timezoneId": ctx["context_options"].get("timezone_id"),
        },
        "camouConfig": config_dict,
        "profileConfig": {
            "fontSpacingSeed": getattr(fonts, "spacing_seed", None) or 0,
            "audioSeed": getattr(audio, "seed", None) or 0,
            "screenWidth": getattr(screen, "width", None) or 1920,
            "screenHeight": getattr(screen, "height", None) or 1080,
            "screenColorDepth": getattr(screen, "color_depth", None) or 24,
            "navigatorPlatform": getattr(navigator, "platform", None) or "",
            "navigatorOscpu": getattr(navigator, "oscpu", None) or "",
            "navigatorUserAgent": getattr(navigator, "user_agent", None) or "",
            "hardwareConcurrency": getattr(navigator, "hardware_concurrency", None) or 0,
            "timezone": getattr(config, "timezone", None) or "",
            "fontList": list(getattr(fonts, "families", None) or []),
            "speechVoices": _voice_names(getattr(voices, "items", None)),
        },
    }


def generate_presets() -> dict[str, Any]:
    try:
        from camoufox.fingerprints import generate_context_fingerprint
        from camoufox.fingerprinting import current_host_target_os
    except ImportError:
        print(
            "ERROR: camoufox Python package not installed.\n"
            "  Run from the repo root with uv, for example:\n"
            "  uv run --group dev --group playwright-tests --locked python __tests__/build-tester/scripts/run_tests.py <binary_path>",
            file=sys.stderr,
        )
        sys.exit(1)

    host_os = current_host_target_os()
    label = "macOS" if host_os == "macos" else "Linux"
    print(f"  Generating 8 {label} per-context profiles...")
    per_context = [convert_preset(generate_context_fingerprint(os=host_os)) for _ in range(8)]

    return {
        "macPerContext": per_context if host_os == "macos" else [],
        "linuxPerContext": per_context if host_os == "linux" else [],
        "macGlobal": None,
        "linuxGlobal": None,
    }


# ─── Preset Injection ─────────────────────────────────────────────────────────

def inject_timezone(preset: dict, timezone: str) -> None:
    preset["initScript"] = re.sub(
        r"w\.setTimezone\(Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone\)",
        f"w.setTimezone({json.dumps(timezone)})",
        preset["initScript"],
    )
    preset["contextOptions"]["timezoneId"] = timezone
    preset["profileConfig"]["timezone"] = timezone
    preset["camouConfig"]["timezone"] = timezone


def inject_webrtc_ip(preset: dict) -> None:
    preset["initScript"] = re.sub(
        r'w\.setWebRTCIPv4\(""\)',
        f"w.setWebRTCIPv4({json.dumps(WEBRTC_TEST_IP)})",
        preset["initScript"],
    )


# ─── Profile Config ───────────────────────────────────────────────────────────

def preset_to_profile_config(preset: dict, name: str, os_type: str, mode: str) -> dict:
    pc = preset["profileConfig"]
    return {
        "name": name,
        "os": os_type,
        "mode": mode,
        "platform": pc["navigatorPlatform"],
        "oscpu": pc["navigatorOscpu"],
        "userAgent": pc["navigatorUserAgent"],
        "hardwareConcurrency": pc["hardwareConcurrency"],
        "screenWidth": pc["screenWidth"],
        "screenHeight": pc["screenHeight"],
        "colorDepth": pc["screenColorDepth"],
        "timezone": pc["timezone"],
    }
