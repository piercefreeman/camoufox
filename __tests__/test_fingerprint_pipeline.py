from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "pythonlib" / "camoufox"


@dataclass(frozen=True)
class FakeNavigator:
    userAgent: str
    platform: str = "MacIntel"
    oscpu: Optional[str] = None


@dataclass(frozen=True)
class FakeScreen:
    width: int = 1500
    height: int = 970
    availWidth: int = 1490
    availHeight: int = 940
    availLeft: int = 0
    availTop: int = 0
    colorDepth: int = 24
    pixelDepth: int = 24
    outerHeight: int = 920
    outerWidth: int = 1400
    innerHeight: int = 880
    innerWidth: int = 1360
    screenX: int = 24
    screenY: int = 0
    devicePixelRatio: float = 2.0


@dataclass(frozen=True)
class FakeFingerprint:
    navigator: FakeNavigator
    screen: FakeScreen


def _install_dependency_shims() -> None:
    if "camoufox.geo" not in sys.modules:
        geo_package = types.ModuleType("camoufox.geo")
        geo_package.__path__ = []
        sys.modules["camoufox.geo"] = geo_package

    if "orjson" not in sys.modules:
        orjson = types.ModuleType("orjson")
        orjson.JSONEncodeError = TypeError
        orjson.dumps = lambda value: json.dumps(value).encode("utf-8")
        orjson.loads = lambda value: json.loads(
            value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value
        )
        sys.modules["orjson"] = orjson

    if "browserforge.fingerprints" not in sys.modules:
        browserforge = types.ModuleType("browserforge")
        fingerprints = types.ModuleType("browserforge.fingerprints")

        @dataclass(frozen=True)
        class Screen:
            max_width: int = 0
            max_height: int = 0

        @dataclass
        class ScreenFingerprint:
            width: int = 0
            height: int = 0
            availWidth: int = 0
            availHeight: int = 0
            availLeft: int = 0
            availTop: int = 0
            colorDepth: int = 24
            pixelDepth: int = 24
            outerHeight: int = 0
            outerWidth: int = 0
            innerHeight: int = 0
            innerWidth: int = 0
            screenX: int = 0
            screenY: int = 0
            devicePixelRatio: float = 1.0

        @dataclass
        class Fingerprint:
            navigator: Any
            screen: Any

        class FingerprintGenerator:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def generate(self, **kwargs: Any) -> Fingerprint:
                raise AssertionError("Tests should stub FingerprintGenerator.generate()")

        fingerprints.Screen = Screen
        fingerprints.ScreenFingerprint = ScreenFingerprint
        fingerprints.Fingerprint = Fingerprint
        fingerprints.FingerprintGenerator = FingerprintGenerator

        browserforge.fingerprints = fingerprints
        sys.modules["browserforge"] = browserforge
        sys.modules["browserforge.fingerprints"] = fingerprints

    if "screeninfo" not in sys.modules:
        screeninfo = types.ModuleType("screeninfo")
        screeninfo.get_monitors = lambda: []
        sys.modules["screeninfo"] = screeninfo

    if "ua_parser" not in sys.modules:
        ua_parser = types.ModuleType("ua_parser")

        def parse_os(user_agent: str) -> Dict[str, str]:
            if "Macintosh" in user_agent:
                return {"family": "Mac OS X"}
            if "Windows" in user_agent:
                return {"family": "Windows"}
            return {"family": "Linux"}

        def parse_user_agent(user_agent: str) -> Dict[str, str]:
            return {"family": "Firefox" if "Firefox/" in user_agent else "Unknown"}

        ua_parser.user_agent_parser = types.SimpleNamespace(
            ParseOS=parse_os,
            ParseUserAgent=parse_user_agent,
        )
        sys.modules["ua_parser"] = ua_parser

    if "camoufox.pkgman" not in sys.modules:
        pkgman = types.ModuleType("camoufox.pkgman")

        def load_yaml(filename: str) -> Dict[str, Any]:
            import yaml

            with open(PACKAGE_ROOT / "assets" / filename, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle)

        pkgman.OS_NAME = "mac"
        pkgman.load_yaml = load_yaml
        pkgman.get_path = lambda file: f"/tmp/{file}"
        pkgman.installed_verstr = lambda: "146.0.1-beta.25"
        pkgman.launch_path = lambda browser_path=None: "/tmp/camoufox"
        sys.modules["camoufox.pkgman"] = pkgman

    if "camoufox._warnings" not in sys.modules:
        warnings_module = types.ModuleType("camoufox._warnings")

        class LeakWarning(RuntimeWarning):
            @staticmethod
            def warn(warning_key: str, i_know_what_im_doing: Optional[bool] = None) -> None:
                return None

        warnings_module.LeakWarning = LeakWarning
        sys.modules["camoufox._warnings"] = warnings_module

    if "camoufox.addons" not in sys.modules:
        addons = types.ModuleType("camoufox.addons")

        class DefaultAddons(Enum):
            UBO = "ubo"

        addons.DefaultAddons = DefaultAddons
        addons.add_default_addons = lambda addons_list, exclude_list=None: None
        addons.confirm_paths = lambda paths: None
        sys.modules["camoufox.addons"] = addons

    if "camoufox.geo.geolocation" not in sys.modules:
        geolocation = types.ModuleType("camoufox.geo.geolocation")
        geolocation.geoip_allowed = lambda: None
        geolocation.get_geolocation = lambda ip, geoip_db=None: types.SimpleNamespace(as_config=lambda: {})
        sys.modules["camoufox.geo.geolocation"] = geolocation
        sys.modules["camoufox.geo"].geolocation = geolocation

    if "camoufox.geo.ip" not in sys.modules:
        ip = types.ModuleType("camoufox.geo.ip")

        @dataclass(frozen=True)
        class Proxy:
            server: str
            username: str = ""
            password: str = ""

            def as_string(self) -> str:
                return self.server

        ip.Proxy = Proxy
        ip.public_ip = lambda proxy=None: "1.2.3.4"
        ip.valid_ipv4 = lambda value: "." in value
        ip.valid_ipv6 = lambda value: ":" in value
        ip.validate_ip = lambda value: None
        sys.modules["camoufox.geo.ip"] = ip
        sys.modules["camoufox.geo"].ip = ip

    if "camoufox.geo.locales" not in sys.modules:
        locales = types.ModuleType("camoufox.geo.locales")

        @dataclass(frozen=True)
        class Locale:
            language: str
            region: str
            script: Optional[str] = None

            @property
            def as_string(self) -> str:
                return f"{self.language}-{self.region}"

        def normalize_locale(locale: str) -> Locale:
            language, region = locale.split("-", 1)
            return Locale(language=language, region=region, script=None)

        locales.Locale = Locale
        locales.normalize_locale = normalize_locale
        locales.handle_locale = lambda locale, ignore_region=False: normalize_locale(locale)
        locales.handle_locales = lambda locales_arg, config: None
        locales.Geolocation = types.SimpleNamespace
        locales.SELECTOR = types.SimpleNamespace(
            from_region=lambda region: normalize_locale(f"en-{region}"),
            from_language=lambda language: normalize_locale(f"{language}-US"),
        )
        sys.modules["camoufox.geo.locales"] = locales
        sys.modules["camoufox.geo"].locales = locales

    if "camoufox.virtdisplay" not in sys.modules:
        virtdisplay = types.ModuleType("camoufox.virtdisplay")

        class VirtualDisplay:
            def kill(self) -> None:
                return None

        virtdisplay.VirtualDisplay = VirtualDisplay
        sys.modules["camoufox.virtdisplay"] = virtdisplay


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def modules() -> tuple[Any, Any, Any]:
    _install_dependency_shims()

    package = types.ModuleType("camoufox")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["camoufox"] = package

    assets = _load_module("camoufox.assets", PACKAGE_ROOT / "assets" / "__init__.py")
    fingerprints = _load_module("camoufox.fingerprints", PACKAGE_ROOT / "fingerprints.py")
    utils = _load_module("camoufox.utils", PACKAGE_ROOT / "utils.py")
    return assets, fingerprints, utils


@pytest.fixture
def fake_host(modules: tuple[Any, Any, Any]) -> Any:
    _ = modules
    host_macos = importlib.import_module("camoufox.fingerprinting.host_macos")
    voices = importlib.import_module("camoufox.fingerprinting.voices")
    return host_macos.MacOSHostAdapter(
        architecture="arm64",
        gpu_vendor="apple",
        gpu_family="apple_m_series",
        bundled_fonts=("Helvetica Neue", "PingFang SC"),
        extra_fonts=("Fira Code", "IBM Plex Sans", "JetBrains Mono"),
        bundled_voices=(voices.Voice("Alex", bundled=True), voices.Voice("Samantha", bundled=True)),
        extra_voices=(voices.Voice("Moira (Enhanced)"), voices.Voice("Karen (Premium)")),
    )


@pytest.fixture
def fake_linux_host(modules: tuple[Any, Any, Any]) -> Any:
    _ = modules
    host_linux = importlib.import_module("camoufox.fingerprinting.host_linux")
    voices = importlib.import_module("camoufox.fingerprinting.voices")
    return host_linux.LinuxHostAdapter(
        architecture="x86_64",
        gpu_vendor="intel",
        gpu_family="intel_iris",
        bundled_fonts=("Arimo", "Cousine"),
        extra_fonts=("Fira Sans", "IBM Plex Sans", "JetBrains Mono"),
        bundled_voices=(voices.Voice("English", bundled=True), voices.Voice("German", bundled=True)),
        extra_voices=(),
    )


@pytest.fixture
def fake_fingerprint() -> FakeFingerprint:
    return FakeFingerprint(
        navigator=FakeNavigator(
            userAgent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:145.0) "
                "Gecko/20100101 Firefox/145.0"
            )
        ),
        screen=FakeScreen(),
    )


@pytest.fixture(autouse=True)
def stable_environment(
    modules: tuple[Any, Any, Any],
    fake_host: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fingerprints, utils = modules
    hosts = importlib.import_module("camoufox.fingerprinting.hosts")
    host_macos = importlib.import_module("camoufox.fingerprinting.host_macos")
    host_linux = importlib.import_module("camoufox.fingerprinting.host_linux")

    monkeypatch.setattr(hosts.sys, "platform", "darwin")
    monkeypatch.setattr(host_macos.MacOSHostAdapter, "_cached", fake_host)
    monkeypatch.setattr(host_linux.LinuxHostAdapter, "_cached", None)
    monkeypatch.setattr(hosts, "_sample_extras", lambda items: list(items[:2]))
    monkeypatch.setattr(fingerprints.FirefoxFingerprintCompiler, "_cached", {})

    monkeypatch.setattr(utils, "OS_NAME", "mac")
    monkeypatch.setattr(utils, "installed_verstr", lambda: "146.0.1-beta.25")
    monkeypatch.setattr(utils, "launch_path", lambda browser_path=None: "/tmp/camoufox")
    monkeypatch.setattr(
        utils,
        "get_path",
        lambda file: f"/tmp/{file}",
    )
    monkeypatch.setattr(utils, "add_default_addons", lambda addons, exclude: None)
    monkeypatch.setattr(utils, "confirm_paths", lambda addons: None)


@pytest.fixture
def fake_linux_fingerprint() -> FakeFingerprint:
    return FakeFingerprint(
        navigator=FakeNavigator(
            userAgent="Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            platform="Linux x86_64",
            oscpu="Linux x86_64",
        ),
        screen=FakeScreen(
            width=1536,
            height=864,
            availWidth=1536,
            availHeight=864,
            outerHeight=832,
            outerWidth=1536,
            innerHeight=800,
            innerWidth=1504,
            devicePixelRatio=1.25,
        ),
    )


def test_from_browserforge_compiles_host_compatible_config(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
) -> None:
    _, fingerprints, _ = modules
    config = fingerprints.from_browserforge(fake_fingerprint, ff_version="146")

    assert config.navigator.user_agent.endswith("Firefox/146.0")
    assert config.navigator.app_version.startswith("5.0 (Macintosh; Intel Mac OS X 10.15")
    assert config.navigator.platform == "MacIntel"
    assert config.navigator.oscpu == "Intel Mac OS X 10.15"
    assert config.screen.width == 1512
    assert config.screen.height == 982
    assert config.fonts.families == ["Helvetica Neue", "PingFang SC", "Fira Code", "IBM Plex Sans"]
    assert config.voices.items == ["Alex", "Samantha", "Moira (Enhanced)", "Karen (Premium)"]
    assert isinstance(config.fonts.spacing_seed, int)
    assert isinstance(config.audio.seed, int)
    assert isinstance(config.canvas.seed, int)


def test_from_preset_keeps_explicit_preset_path_host_safe(modules: tuple[Any, Any, Any]) -> None:
    _, fingerprints, _ = modules
    preset = {
        "navigator": {
            "platform": "MacIntel",
            "userAgent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:145.0) "
                "Gecko/20100101 Firefox/145.0"
            ),
        },
        "screen": {
            "width": 1720,
            "height": 1100,
            "availWidth": 1700,
            "availHeight": 1060,
            "colorDepth": 24,
            "pixelDepth": 24,
            "devicePixelRatio": 2.0,
        },
        "timezone": "America/New_York",
    }

    config = fingerprints.from_preset(preset, ff_version="146")

    assert config.navigator.user_agent.endswith("Firefox/146.0")
    assert config.navigator.oscpu == "Intel Mac OS X 10.15"
    assert config.screen.width == 1728
    assert config.screen.height == 1117
    assert config.window.device_pixel_ratio == 2.0
    assert config.timezone == "America/New_York"
    assert config.fonts.families == ["Helvetica Neue", "PingFang SC", "Fira Code", "IBM Plex Sans"]
    assert config.voices.items == ["Alex", "Samantha", "Moira (Enhanced)", "Karen (Premium)"]


def test_generate_context_fingerprint_emits_debug_logs(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, fingerprints, _ = modules
    monkeypatch.setattr(fingerprints, "generate_fingerprint", lambda **_: fake_fingerprint)

    result = fingerprints.generate_context_fingerprint(debug=True)
    output = capsys.readouterr().out

    assert "[camoufox:fingerprint] Preparing fingerprinted browser context." in output
    assert "[camoufox:fingerprint] Generating BrowserForge Firefox skeleton." in output
    assert "[camoufox:fingerprint] Context options ready:" in output
    assert result["context_options"]["user_agent"].endswith("Firefox/145.0")


def test_generate_context_fingerprint_reuses_supplied_browserforge_fingerprint(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fingerprints, _ = modules

    def _unexpected_generate(**_: Any) -> Any:
        raise AssertionError("generate_fingerprint should not be called when a fingerprint is supplied")

    monkeypatch.setattr(fingerprints, "generate_fingerprint", _unexpected_generate)

    result = fingerprints.generate_context_fingerprint(fingerprint=fake_fingerprint, ff_version="146")

    assert result["config"].navigator.user_agent.endswith("Firefox/146.0")
    assert result["context_options"]["viewport"] == {"width": 1512, "height": 954}


def test_launch_options_does_not_warn_for_camoufox_generated_fingerprint(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fingerprints, utils = modules
    monkeypatch.setattr(
        fingerprints.FirefoxFingerprintCompiler.current().generator,
        "generate",
        lambda **_: fake_fingerprint,
    )

    generated_fingerprint = fingerprints.generate_fingerprint()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        utils.launch_options(fingerprint=generated_fingerprint, env={"TEST_ENV": "1"}, headless=True)

    assert not [warning for warning in caught if issubclass(warning.category, RuntimeWarning)]


def test_launch_options_generates_full_config_payload(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, utils = modules
    monkeypatch.setattr(utils, "generate_fingerprint", lambda **_: fake_fingerprint)

    options = utils.launch_options(
        config={"webGl": {"vendor": "spoofed"}},
        env={"TEST_ENV": "1"},
        headless=True,
        locale="en-US",
    )
    payload = _decode_camou_config(options["env"])

    assert options["executable_path"] == "/tmp/camoufox"
    assert options["headless"] is True
    assert options["env"]["TEST_ENV"] == "1"
    assert payload["navigator"]["userAgent"].endswith("Firefox/146.0")
    assert payload["navigator"]["language"] == "en-US"
    assert payload["locale"]["language"] == "en"
    assert payload["locale"]["region"] == "US"
    assert payload["fonts"]["families"] == [
        "Helvetica Neue",
        "PingFang SC",
        "Fira Code",
        "IBM Plex Sans",
    ]
    assert payload["voices"]["items"] == ["Alex", "Samantha", "Moira (Enhanced)", "Karen (Premium)"]
    assert "webGl" not in payload
    assert 1 <= payload["window"]["history"]["length"] <= 5


def test_from_browserforge_compiles_linux_host_compatible_config(
    modules: tuple[Any, Any, Any],
    fake_linux_host: Any,
    fake_linux_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fingerprints, utils = modules
    hosts = importlib.import_module("camoufox.fingerprinting.hosts")
    host_macos = importlib.import_module("camoufox.fingerprinting.host_macos")
    host_linux = importlib.import_module("camoufox.fingerprinting.host_linux")

    monkeypatch.setattr(hosts.sys, "platform", "linux")
    monkeypatch.setattr(host_macos.MacOSHostAdapter, "_cached", None)
    monkeypatch.setattr(host_linux.LinuxHostAdapter, "_cached", fake_linux_host)
    monkeypatch.setattr(fingerprints.FirefoxFingerprintCompiler, "_cached", {})
    monkeypatch.setattr(utils, "OS_NAME", "lin")

    config = fingerprints.from_browserforge(fake_linux_fingerprint, ff_version="146")

    assert config.navigator.user_agent.endswith("Firefox/146.0")
    assert config.navigator.app_version.startswith("5.0 (X11; Linux x86_64")
    assert config.navigator.platform == "Linux x86_64"
    assert config.navigator.oscpu == "Linux x86_64"
    assert config.screen.width == 1536
    assert config.screen.height == 864
    assert config.fonts.families == ["Arimo", "Cousine", "Fira Sans", "IBM Plex Sans"]
    assert config.voices.items == ["English", "German"]


def test_launch_options_defaults_to_linux_host_target(
    modules: tuple[Any, Any, Any],
    fake_linux_host: Any,
    fake_linux_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, fingerprints, utils = modules
    hosts = importlib.import_module("camoufox.fingerprinting.hosts")
    host_macos = importlib.import_module("camoufox.fingerprinting.host_macos")
    host_linux = importlib.import_module("camoufox.fingerprinting.host_linux")

    monkeypatch.setattr(hosts.sys, "platform", "linux")
    monkeypatch.setattr(host_macos.MacOSHostAdapter, "_cached", None)
    monkeypatch.setattr(host_linux.LinuxHostAdapter, "_cached", fake_linux_host)
    monkeypatch.setattr(fingerprints.FirefoxFingerprintCompiler, "_cached", {})
    monkeypatch.setattr(utils, "OS_NAME", "lin")
    monkeypatch.setattr(utils, "generate_fingerprint", lambda **_: fake_linux_fingerprint)
    fontconfig_root = tmp_path / "fontconfigs" / "linux"
    fontconfig_root.mkdir(parents=True)
    (fontconfig_root / "fonts.conf").write_text('<fontconfig><dir prefix="cwd">fonts</dir></fontconfig>')
    monkeypatch.setattr(utils, "get_path", lambda file: str(tmp_path / file))

    options = utils.launch_options(env={"TEST_ENV": "1"}, headless=True)
    payload = _decode_camou_config(options["env"])

    assert utils._normalize_requested_os(None) == "linux"
    assert payload["navigator"]["platform"] == "Linux x86_64"
    assert payload["navigator"]["oscpu"] == "Linux x86_64"
    assert payload["fonts"]["families"] == ["Arimo", "Cousine", "Fira Sans", "IBM Plex Sans"]


def test_launch_options_rejects_literal_readme_placeholder_path(
    modules: tuple[Any, Any, Any],
) -> None:
    _, _, utils = modules

    with pytest.raises(FileNotFoundError, match="README placeholder was used literally"):
        utils.launch_options(
            executable_path="/tmp/camoufox-<version>-<release>/Camoufox.app/Contents/MacOS/camoufox"
        )


def test_launch_options_reads_version_from_macos_bundle(
    modules: tuple[Any, Any, Any],
    fake_fingerprint: FakeFingerprint,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, utils = modules
    monkeypatch.setattr(utils, "generate_fingerprint", lambda **_: fake_fingerprint)
    monkeypatch.setattr(utils, "installed_verstr", lambda: "142.0.0-beta.1")

    executable_path = tmp_path / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")

    resources = executable_path.parent.parent / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "application.ini").write_text(
        "[App]\nVersion=146.0.1-beta.25\n",
        encoding="utf-8",
    )

    options = utils.launch_options(executable_path=executable_path, env={"TEST_ENV": "1"}, headless=True)
    payload = _decode_camou_config(options["env"])

    assert options["executable_path"] == str(executable_path)
    assert payload["navigator"]["userAgent"].endswith("Firefox/146.0")


def test_get_asset_by_name_returns_packaged_path(modules: tuple[Any, Any, Any]) -> None:
    assets, _, _ = modules

    asset_path = assets.get_asset_by_name("launchServer.js")

    assert asset_path.name == "launchServer.js"
    assert asset_path.is_file()
    assert asset_path.parent == PACKAGE_ROOT / "assets"


def _decode_camou_config(env: Dict[str, Any]) -> Dict[str, Any]:
    with open(env["CAMOU_CONFIG_PATH"], encoding="utf-8") as handle:
        return json.load(handle)
