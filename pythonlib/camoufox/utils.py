from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from os import environ
from os.path import abspath
from pathlib import Path
from pprint import pprint
from random import randint, randrange
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union, cast

import orjson
from browserforge.fingerprints import Fingerprint, Screen
from screeninfo import get_monitors
from typing_extensions import TypeAlias
from ua_parser import user_agent_parser

from ._warnings import LeakWarning
from .addons import DefaultAddons, add_default_addons, confirm_paths
from .exceptions import InvalidOS, InvalidPropertyType, NonFirefoxFingerprint
from .fingerprints import from_browserforge, from_preset, generate_fingerprint, is_generated_fingerprint
from .geolocation import geoip_allowed, get_geolocation
from .ip import Proxy, public_ip, valid_ipv4, valid_ipv6
from .locales import handle_locales
from .pkgman import OS_NAME, get_path, installed_verstr, launch_path
from .virtdisplay import VirtualDisplay

ListOrString: TypeAlias = Union[Tuple[str, ...], List[str], str]

CACHE_PREFS = {
    "browser.cache.disk.smart_size.enabled": True,
    "browser.cache.disk_cache_ssl": True,
    "browser.cache.memory.enable": True,
    "browser.sessionhistory.max_entries": 10,
    "browser.sessionhistory.max_total_viewers": -1,
}


def launch_options(
    *,
    config: Optional[Dict[str, Any]] = None,
    os: Optional[ListOrString] = None,
    block_images: Optional[bool] = None,
    block_webrtc: Optional[bool] = None,
    block_webgl: Optional[bool] = None,
    disable_coop: Optional[bool] = None,
    webgl_config: Optional[Tuple[str, str]] = None,
    geoip: Optional[Union[str, bool]] = None,
    geoip_db: Optional[str] = None,
    humanize: Optional[Union[bool, float]] = None,
    locale: Optional[Union[str, List[str]]] = None,
    addons: Optional[List[str]] = None,
    fonts: Optional[List[str]] = None,
    custom_fonts_only: Optional[bool] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    window: Optional[Tuple[int, int]] = None,
    fingerprint: Optional[Fingerprint] = None,
    fingerprint_preset: Optional[Dict[str, Any]] = None,
    ff_version: Optional[int] = None,
    headless: Optional[bool] = None,
    main_world_eval: Optional[bool] = None,
    executable_path: Optional[Union[str, Path]] = None,
    browser: Optional[str] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    proxy: Optional[Dict[str, str]] = None,
    enable_cache: Optional[bool] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
    i_know_what_im_doing: Optional[bool] = None,
    debug: Optional[bool] = None,
    virtual_display: Optional[str] = None,
    **launch_options: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the Playwright launch options for Camoufox.

    The active fingerprint path is intentionally small:
    BrowserForge supplies the Firefox skeleton, and Camoufox only layers in
    host-compatible macOS values on top of it.

    `fingerprint_preset` is now an explicit preset dictionary only. Camoufox no
    longer ships or samples a bundled preset corpus through this API.
    """
    return _LaunchOptionBuilder(
        config=config,
        requested_os=os,
        block_images=block_images,
        block_webrtc=block_webrtc,
        block_webgl=block_webgl,
        disable_coop=disable_coop,
        webgl_config=webgl_config,
        geoip=geoip,
        geoip_db=geoip_db,
        humanize=humanize,
        locale=locale,
        addons=addons,
        fonts=fonts,
        custom_fonts_only=custom_fonts_only,
        exclude_addons=exclude_addons,
        screen=screen,
        window=window,
        fingerprint=fingerprint,
        fingerprint_preset=fingerprint_preset,
        ff_version=ff_version,
        headless=headless,
        main_world_eval=main_world_eval,
        executable_path=executable_path,
        browser=browser,
        firefox_user_prefs=firefox_user_prefs,
        proxy=proxy,
        enable_cache=enable_cache,
        args=args,
        env=env,
        i_know_what_im_doing=i_know_what_im_doing,
        debug=debug,
        virtual_display=virtual_display,
        extra_launch_options=launch_options,
    ).build()


async def async_attach_vd(
    browser: Any,
    virtual_display: Optional[VirtualDisplay] = None,
) -> Any:  # type: ignore
    """
    Attach a virtual display lifecycle to an async Playwright browser/context.

    The returned object is the same Playwright instance with `.close()`
    wrapped so that the `VirtualDisplay` is always torn down.
    """
    if not virtual_display:
        return browser

    close = browser.close

    async def wrapped_close(*args: Any, **kwargs: Any) -> None:
        try:
            await close(*args, **kwargs)
        finally:
            virtual_display.kill()

    browser.close = wrapped_close
    browser._virtual_display = virtual_display
    return browser


def sync_attach_vd(
    browser: Any,
    virtual_display: Optional[VirtualDisplay] = None,
) -> Any:  # type: ignore
    """
    Attach a virtual display lifecycle to a sync Playwright browser/context.

    The returned object is the same Playwright instance with `.close()`
    wrapped so that the `VirtualDisplay` is always torn down.
    """
    if not virtual_display:
        return browser

    close = browser.close

    def wrapped_close(*args: Any, **kwargs: Any) -> None:
        try:
            close(*args, **kwargs)
        finally:
            virtual_display.kill()

    browser.close = wrapped_close
    browser._virtual_display = virtual_display
    return browser


def get_env_vars(
    config_map: Dict[str, Any],
    user_agent_os: str,
) -> Dict[str, Union[str, float, bool]]:
    """
    Serialize a config map into the `CAMOU_CONFIG_N` environment variables.

    The browser bootstrap code reads these chunks and reconstructs the final
    JSON payload before Firefox starts.
    """
    encoded = orjson.dumps(config_map).decode("utf-8")
    chunk_size = 2047 if OS_NAME == "win" else 32767

    env_vars: Dict[str, Union[str, float, bool]] = {}
    for index, start in enumerate(range(0, len(encoded), chunk_size), start=1):
        env_vars[f"CAMOU_CONFIG_{index}"] = encoded[start : start + chunk_size]

    if OS_NAME == "lin":
        directory_map = {"lin": "linux", "mac": "macos", "win": "windows"}
        fontconfig_path = get_path(os.path.join("fontconfigs", directory_map[user_agent_os]))
        fonts_conf = os.path.join(fontconfig_path, "fonts.conf")
        if not os.path.exists(fonts_conf):
            raise FileNotFoundError(
                f"fonts.conf not found in {fontconfig_path}. The Camoufox bundle is incomplete."
            )
        env_vars["FONTCONFIG_FILE"] = _generate_fontconfig(fontconfig_path)

    return env_vars


def validate_config(config_map: Dict[str, Any], path: Optional[Path] = None) -> None:
    """
    Validate a config map against the browser `properties.json` schema.

    Unknown keys are ignored so newer Python code can still talk to slightly
    older browser builds without failing hard on unsupported properties.
    """
    property_types = _load_properties(path=path)
    for key, value in config_map.items():
        expected_type = property_types.get(key)
        if not expected_type:
            print(f"Skipping unknown patch {key} : {value}")
            continue
        if not validate_type(value, expected_type):
            raise InvalidPropertyType(
                f"Invalid type for property {key}. Expected {expected_type}, got {type(value).__name__}"
            )


def validate_type(value: Any, expected_type: str) -> bool:
    """
    Validate a single value against the browser property type schema.
    """
    if expected_type == "str":
        return isinstance(value, str)
    if expected_type == "int":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if expected_type == "uint":
        return (
            isinstance(value, int) or (isinstance(value, float) and value.is_integer())
        ) and value >= 0
    if expected_type == "double":
        return isinstance(value, (float, int))
    if expected_type == "bool":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "dict":
        return isinstance(value, dict)
    return False


@dataclass
class _LaunchOptionBuilder:
    config: Optional[Dict[str, Any]]
    requested_os: Optional[ListOrString]
    block_images: Optional[bool]
    block_webrtc: Optional[bool]
    block_webgl: Optional[bool]
    disable_coop: Optional[bool]
    webgl_config: Optional[Tuple[str, str]]
    geoip: Optional[Union[str, bool]]
    geoip_db: Optional[str]
    humanize: Optional[Union[bool, float]]
    locale: Optional[Union[str, List[str]]]
    addons: Optional[List[str]]
    fonts: Optional[List[str]]
    custom_fonts_only: Optional[bool]
    exclude_addons: Optional[List[DefaultAddons]]
    screen: Optional[Screen]
    window: Optional[Tuple[int, int]]
    fingerprint: Optional[Fingerprint]
    fingerprint_preset: Optional[Dict[str, Any]]
    ff_version: Optional[int]
    headless: Optional[bool]
    main_world_eval: Optional[bool]
    executable_path: Optional[Union[str, Path]]
    browser: Optional[str]
    firefox_user_prefs: Optional[Dict[str, Any]]
    proxy: Optional[Dict[str, str]]
    enable_cache: Optional[bool]
    args: Optional[List[str]]
    env: Optional[Dict[str, Union[str, float, bool]]]
    i_know_what_im_doing: Optional[bool]
    debug: Optional[bool]
    virtual_display: Optional[str]
    extra_launch_options: Dict[str, Any] = field(default_factory=dict)

    _manual_fonts: List[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        original_config = dict(self.config or {})
        self._manual_fonts = _unique_strings(
            [*_string_list(original_config.get("fonts")), *(self.fonts or [])]
        )

        self.config = original_config
        self.addons = list(self.addons or [])
        self.args = list(self.args or [])
        self.firefox_user_prefs = dict(self.firefox_user_prefs or {})
        self.fonts = list(self.fonts or [])
        self.env = dict(self.env or cast(Dict[str, Union[str, float, bool]], dict(environ)))
        self.extra_launch_options = dict(self.extra_launch_options)

        if self.headless is None:
            self.headless = False
        if self.custom_fonts_only is None:
            self.custom_fonts_only = False
        if self.i_know_what_im_doing is None:
            self.i_know_what_im_doing = False

        if isinstance(self.executable_path, str):
            self.executable_path = Path(abspath(self.executable_path))

    def build(self) -> Dict[str, Any]:
        if self.virtual_display:
            self.env["DISPLAY"] = self.virtual_display

        if not self.i_know_what_im_doing:
            _warn_manual_config(self.config)

        resolved_executable_path = self._resolve_executable_path()
        resolved_executable = Path(resolved_executable_path)
        _debug_log(self.debug, f"Using executable path: {resolved_executable}")

        target_os = _normalize_requested_os(self.requested_os)
        _debug_log(self.debug, f"Target fingerprint OS: {target_os}")
        self._configure_addons()

        ff_version_str = self._resolve_firefox_version(resolved_executable)
        _debug_log(self.debug, f"Resolved Firefox version: {ff_version_str}")
        generated_config = self._build_generated_config(target_os, ff_version_str)
        _merge_missing(self.config, generated_config)
        _strip_gpu_overrides(self.config)

        self._apply_fonts()
        self._apply_launch_defaults()
        self._apply_geoip()
        self._apply_locale()
        self._apply_humanize()
        self._apply_firefox_preferences()

        if self.debug:
            print("[DEBUG] Config:")
            pprint(self.config)

        _debug_log(self.debug, "Validating generated config against browser properties.json.")
        validate_config(self.config, path=resolved_executable)

        result = {
            "args": self.args,
            "env": {
                **get_env_vars(self.config, _user_agent_os(self.config)),
                **self.env,
            },
            "executable_path": resolved_executable_path,
            "firefox_user_prefs": self.firefox_user_prefs,
            "headless": self.headless,
            **self.extra_launch_options,
        }
        if self.proxy is not None:
            result["proxy"] = self.proxy
        return result

    def _configure_addons(self) -> None:
        add_default_addons(self.addons, self.exclude_addons)
        if not self.addons:
            return

        confirm_paths(self.addons)
        self.config["addons"] = self.addons

    def _resolve_firefox_version(self, executable_path: Path) -> str:
        if self.ff_version is None:
            bundle_version = _load_bundle_version(executable_path)
            if bundle_version:
                return bundle_version.split(".", 1)[0]
            return installed_verstr().split(".", 1)[0]

        LeakWarning.warn("ff_version", self.i_know_what_im_doing)
        return str(self.ff_version)

    def _build_generated_config(self, target_os: str, ff_version: str) -> Dict[str, Any]:
        if self.fingerprint is not None:
            if not self.i_know_what_im_doing:
                _check_custom_fingerprint(self.fingerprint)
            _debug_log(self.debug, "Using caller-supplied BrowserForge fingerprint.")
            return from_browserforge(self.fingerprint, ff_version)

        preset = self._resolve_preset()
        if preset is not None:
            _debug_log(self.debug, "Using caller-supplied fingerprint preset.")
            return from_preset(preset, ff_version)

        _debug_log(self.debug, "Generating BrowserForge fingerprint for browser launch.")
        fingerprint = generate_fingerprint(
            os=target_os,
            screen=self.screen or _screen_constraints(self.headless or "DISPLAY" in self.env),
            window=self.window,
            debug=bool(self.debug),
        )
        return from_browserforge(fingerprint, ff_version)

    def _resolve_preset(self) -> Optional[Dict[str, Any]]:
        if self.fingerprint_preset is None:
            return None
        if isinstance(self.fingerprint_preset, bool):
            raise TypeError(
                "fingerprint_preset no longer accepts booleans. Pass an explicit preset dict or omit the argument."
            )
        return self.fingerprint_preset

    def _apply_fonts(self) -> None:
        if self.custom_fonts_only:
            self.firefox_user_prefs["gfx.bundled-fonts.activate"] = 0
            if not self._manual_fonts:
                raise ValueError("No custom fonts were passed, but `custom_fonts_only` is enabled.")
            self.config["fonts"] = self._manual_fonts
            return

        if self._manual_fonts:
            self.config["fonts"] = _unique_strings(
                [*_string_list(self.config.get("fonts")), *self._manual_fonts]
            )

    def _apply_launch_defaults(self) -> None:
        _set_if_missing(self.config, "window.history.length", randrange(1, 6))  # nosec
        _set_if_missing(self.config, "fonts:spacing_seed", randint(1, 4_294_967_295))  # nosec
        _set_if_missing(self.config, "audio:seed", randint(1, 4_294_967_295))  # nosec
        _set_if_missing(self.config, "canvas:seed", randint(1, 4_294_967_295))  # nosec

    def _apply_geoip(self) -> None:
        if not self.geoip:
            if (
                self.proxy
                and "localhost" not in self.proxy.get("server", "")
                and not _is_domain_set(self.config, "geolocation")
            ):
                LeakWarning.warn("proxy_without_geoip")
            return

        geoip_allowed()
        ip_address = self.geoip
        if ip_address is True:
            ip_address = public_ip(Proxy(**self.proxy).as_string()) if self.proxy else public_ip()

        assert isinstance(ip_address, str)

        if not self.block_webrtc:
            if valid_ipv4(ip_address):
                _set_if_missing(self.config, "webrtc:ipv4", ip_address)
                self.firefox_user_prefs["network.dns.disableIPv6"] = True
            elif valid_ipv6(ip_address):
                _set_if_missing(self.config, "webrtc:ipv6", ip_address)

        geolocation = get_geolocation(ip_address, geoip_db=self.geoip_db)
        for key, value in geolocation.as_config().items():
            if key in {"timezone", "locale:language", "locale:region", "locale:script"}:
                self.config.setdefault(key, value)
            else:
                self.config[key] = value

    def _apply_locale(self) -> None:
        if self.locale:
            handle_locales(self.locale, self.config)

    def _apply_humanize(self) -> None:
        if self.humanize:
            _set_if_missing(self.config, "humanize", True)
            if isinstance(self.humanize, (int, float)):
                _set_if_missing(self.config, "humanize:maxTime", self.humanize)

        if self.main_world_eval:
            _set_if_missing(self.config, "allowMainWorld", True)

    def _apply_firefox_preferences(self) -> None:
        if self.block_images:
            LeakWarning.warn("block_images", self.i_know_what_im_doing)
            self.firefox_user_prefs["permissions.default.image"] = 2

        if self.block_webrtc:
            self.firefox_user_prefs["media.peerconnection.enabled"] = False

        if self.disable_coop:
            LeakWarning.warn("disable_coop", self.i_know_what_im_doing)
            self.firefox_user_prefs["browser.tabs.remote.useCrossOriginOpenerPolicy"] = False

        allow_webgl = self.extra_launch_options.pop("allow_webgl", True)
        if self.block_webgl or allow_webgl is False:
            self.firefox_user_prefs["webgl.disabled"] = True
            LeakWarning.warn("block_webgl", self.i_know_what_im_doing)
        elif self.webgl_config:
            # GPU identity should come from the real host, not from injected strings.
            pass

        if self.enable_cache:
            _merge_missing(self.firefox_user_prefs, CACHE_PREFS)

    def _resolve_executable_path(self) -> str:
        if self.executable_path is not None:
            executable_path = Path(self.executable_path)
            if not executable_path.exists():
                placeholder_hint = ""
                executable_path_str = str(executable_path)
                if "<version>" in executable_path_str or "<release>" in executable_path_str:
                    placeholder_hint = (
                        " The README placeholder was used literally. Run `source upstream.sh` first, "
                        "then build the path with `$version` and `$release`."
                    )
                raise FileNotFoundError(
                    f"Camoufox executable does not exist: {executable_path}.{placeholder_hint}"
                )
            return str(executable_path)

        if self.browser:
            from .multiversion import find_installed_version

            browser_path = find_installed_version(self.browser)
            if not browser_path:
                raise ValueError(
                    f"Browser version '{self.browser}' not found. Run `camoufox list` to see installed versions."
                )
            return launch_path(browser_path)

        return launch_path()


def _generate_fontconfig(fontconfig_path: str) -> str:
    import hashlib

    fonts_dir = get_path("fonts")
    fonts_conf_src = os.path.join(fontconfig_path, "fonts.conf")

    with open(fonts_conf_src, "r", encoding="utf-8") as handle:
        conf_content = handle.read()

    conf_content = conf_content.replace(
        '<dir prefix="cwd">fonts</dir>',
        f"<dir>{fonts_dir}</dir>",
    )

    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "camoufox", "fontconfig")
    os.makedirs(cache_dir, exist_ok=True)

    content_hash = hashlib.sha256(conf_content.encode()).hexdigest()[:12]
    runtime_conf = os.path.join(cache_dir, f"fonts-{content_hash}.conf")
    if not os.path.exists(runtime_conf):
        with open(runtime_conf, "w", encoding="utf-8") as handle:
            handle.write(conf_content)

    return runtime_conf


def _load_properties(path: Optional[Path] = None) -> Dict[str, str]:
    if path:
        prop_file = _resolve_bundle_resource(path, "properties.json")
        if not prop_file.exists():
            prop_file = Path(get_path("properties.json"))
    else:
        prop_file = Path(get_path("properties.json"))

    with open(prop_file, "rb") as handle:
        properties = orjson.loads(handle.read())
    return {item["property"]: item["type"] for item in properties}


def _normalize_requested_os(requested_os: Optional[ListOrString]) -> str:
    if requested_os is None:
        return "macos"

    values = [requested_os] if isinstance(requested_os, str) else list(requested_os)
    _check_valid_os(values)
    if any(value != "macos" for value in values):
        raise NotImplementedError("Camoufox currently supports only macOS-compatible fingerprint generation.")
    return "macos"


def _user_agent_os(config: Dict[str, Any]) -> Literal["mac", "win", "lin"]:
    user_agent = config.get("navigator.userAgent")
    if isinstance(user_agent, str):
        return _determine_ua_os(user_agent)
    return OS_NAME


def _determine_ua_os(user_agent: str) -> Literal["mac", "win", "lin"]:
    family = user_agent_parser.ParseOS(user_agent).get("family")
    if not family:
        raise ValueError("Could not determine OS from user agent")
    if family.startswith("Mac"):
        return "mac"
    if family.startswith("Windows"):
        return "win"
    return "lin"


def _screen_constraints(headless: Optional[bool] = None) -> Optional[Screen]:
    if headless is False:
        return None

    try:
        monitors = get_monitors()
    except Exception:
        return None
    if not monitors:
        return None

    monitor = max(monitors, key=lambda item: item.width * item.height)
    return Screen(max_width=monitor.width, max_height=monitor.height)


def _check_custom_fingerprint(fingerprint: Fingerprint) -> None:
    if is_generated_fingerprint(fingerprint):
        return

    browser_name = user_agent_parser.ParseUserAgent(fingerprint.navigator.userAgent).get(
        "family",
        "Non-Firefox",
    )
    if browser_name != "Firefox":
        raise NonFirefoxFingerprint(
            f'"{browser_name}" fingerprints are not supported in Camoufox. '
            "Using fingerprints from a browser other than Firefox will lead to detection. "
            "If this is intentional, pass `i_know_what_im_doing=True`."
        )
    LeakWarning.warn("custom_fingerprint", False)


def _check_valid_os(os_value: ListOrString) -> None:
    if not isinstance(os_value, str):
        for entry in os_value:
            _check_valid_os(entry)
        return

    if not os_value.islower():
        raise InvalidOS(f"OS values must be lowercase: '{os_value}'")
    if os_value not in ("windows", "macos", "linux"):
        raise InvalidOS(f"Camoufox does not support the OS: '{os_value}'")


def _merge_missing(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key, value in source.items():
        target.setdefault(key, value)


def _set_if_missing(target: Dict[str, Any], key: str, value: Any) -> None:
    target.setdefault(key, value)


def _strip_gpu_overrides(config: Dict[str, Any]) -> None:
    for key in list(config):
        if key.startswith("webGl:") or key.startswith("webGl2:"):
            del config[key]


def _warn_manual_config(config: Dict[str, Any]) -> None:
    if _is_domain_set(config, "navigator.language", "navigator.languages", "headers.Accept-Language", "locale:"):
        LeakWarning.warn("locale", False)
    if _is_domain_set(config, "geolocation:", "timezone"):
        LeakWarning.warn("geolocation", False)
    if _is_domain_set(config, "headers.User-Agent"):
        LeakWarning.warn("header-ua", False)
    if _is_domain_set(config, "navigator."):
        LeakWarning.warn("navigator", False)
    if _is_domain_set(config, "screen.", "window.", "document.body."):
        LeakWarning.warn("viewport", False)


def _is_domain_set(config: Dict[str, Any], *properties: str) -> bool:
    for prop in properties:
        if prop[-1] in (".", ":"):
            if any(key.startswith(prop) for key in config):
                return True
        elif prop in config:
            return True
    return False


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _unique_strings(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _resolve_bundle_resource(executable_path: Path, filename: str) -> Path:
    candidates = [executable_path.parent / filename]
    if executable_path.parent.name == "MacOS" and executable_path.parent.parent.name == "Contents":
        candidates.insert(0, executable_path.parent.parent / "Resources" / filename)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_bundle_version(executable_path: Path) -> Optional[str]:
    application_ini = _resolve_bundle_resource(executable_path, "application.ini")
    if not application_ini.exists():
        return None

    parser = configparser.ConfigParser()
    parser.read(application_ini, encoding="utf-8")
    return parser.get("App", "Version", fallback=None)


def _debug_log(enabled: Optional[bool], message: str) -> None:
    if enabled:
        print(f"[camoufox:launch] {message}")
