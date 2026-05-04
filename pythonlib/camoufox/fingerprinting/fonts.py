from __future__ import annotations

from dataclasses import dataclass, field

from .common import LINUX, MACOS, WINDOWS, TargetOS, empty_target_os_set, target_os_set


@dataclass(frozen=True)
class Font:
    """
    Catalog entry for a spoofable font family.

    `target_os` is the set of OS identities this family legitimately belongs to.
    `marker` marks high-signal families that fingerprinting suites use to confirm
    the claimed OS; the host adapter will force-include them when they are
    locally installed.
    `leak_signal` marks families that should be denied when sampling for a
    different target OS; `blocked_families_for_target_os()` builds that denylist
    and `HostFingerprintAdapter.sample_fonts()` enforces it.

    `path` and `is_system` are probe-time annotations attached after local host
    discovery and are not part of the static catalog definition.
    """
    family: str
    aliases: tuple[str, ...] = ()
    target_os: frozenset[TargetOS] = field(default_factory=empty_target_os_set)

    # Marker families are re-added after random sampling when the local host
    # actually has them, so the emitted profile retains expected OS-ID signals.
    marker: bool = False

    # Leak-signal families are excluded from profiles for other target OSes.
    # This is only consulted during final sampling, not during host probing.
    leak_signal: bool = False

    # Probe-time metadata populated by host-specific discovery code.
    path: str | None = None
    is_system: bool | None = None

    def names(self) -> tuple[str, ...]:
        return (self.family, *self.aliases)


_FONT_DEFINITIONS: tuple[Font, ...] = (
    Font("Helvetica Neue", target_os=target_os_set(MACOS), marker=True, leak_signal=True),
    Font("PingFang HK", target_os=target_os_set(MACOS), marker=True, leak_signal=True),
    Font("PingFang SC", target_os=target_os_set(MACOS), marker=True, leak_signal=True),
    Font("PingFang TC", target_os=target_os_set(MACOS), marker=True, leak_signal=True),
    Font("Geneva", target_os=target_os_set(MACOS), leak_signal=True),
    Font("Lucida Grande", target_os=target_os_set(MACOS)),
    Font("Menlo", target_os=target_os_set(MACOS)),
    Font("Monaco", target_os=target_os_set(MACOS)),
    Font("Arimo", target_os=target_os_set(LINUX), marker=True, leak_signal=True),
    Font("Cousine", target_os=target_os_set(LINUX), marker=True, leak_signal=True),
    Font("Tinos", target_os=target_os_set(LINUX), leak_signal=True),
    Font("Twemoji Mozilla", target_os=target_os_set(LINUX)),
    Font("Cantarell", target_os=target_os_set(LINUX), leak_signal=True),
    Font("Ubuntu", target_os=target_os_set(LINUX), leak_signal=True),
    Font("DejaVu Sans", target_os=target_os_set(LINUX), leak_signal=True),
    Font("Liberation Sans", target_os=target_os_set(LINUX), leak_signal=True),
    Font("Noto Color Emoji", target_os=target_os_set(LINUX), leak_signal=True),
    Font("Segoe UI", target_os=target_os_set(WINDOWS), marker=True, leak_signal=True),
    Font("Tahoma", target_os=target_os_set(WINDOWS)),
    Font("Cambria Math", target_os=target_os_set(WINDOWS), marker=True, leak_signal=True),
    Font("Nirmala UI", target_os=target_os_set(WINDOWS), marker=True, leak_signal=True),
    Font("Leelawadee UI", target_os=target_os_set(WINDOWS), marker=True, leak_signal=True),
    Font(
        "HoloLens MDL2 Assets",
        target_os=target_os_set(WINDOWS),
        marker=True,
        leak_signal=True,
    ),
    Font(
        "Segoe Fluent Icons",
        target_os=target_os_set(WINDOWS),
        marker=True,
        leak_signal=True,
    ),
)

_DEFAULT_FONT_FAMILIES: dict[TargetOS, tuple[str, ...]] = {
    MACOS: (
        "Arial",
        "Arial Black",
        "Arial Hebrew",
        "Arial Narrow",
        "Arial Rounded MT Bold",
        "Apple Braille",
        "Apple Chancery",
        "Apple Color Emoji",
        "Apple SD Gothic Neo",
        "Apple Symbols",
        "AppleGothic",
        "Avenir",
        "Avenir Next",
        "Avenir Next Condensed",
        "Baskerville",
        "Big Caslon",
        "Bodoni 72",
        "Bodoni 72 Oldstyle",
        "Bodoni 72 Smallcaps",
        "Bodoni Ornaments",
        "Bradley Hand",
        "Chalkboard",
        "Chalkboard SE",
        "Chalkduster",
        "Charter",
        "Cochin",
        "Comic Sans MS",
        "Copperplate",
        "Helvetica",
        "Times New Roman",
        "Courier New",
        "Damascus",
        "Devanagari Sangam MN",
        "Didot",
        "DIN Alternate",
        "DIN Condensed",
        "Euphemia UCAS",
        "Futura",
        "Galvji",
        "Geeza Pro",
        "Geneva",
        "Verdana",
        "Georgia",
        "Trebuchet MS",
        "Gill Sans",
        "Helvetica Neue",
        "Herculanum",
        "Hiragino Maru Gothic ProN",
        "Hiragino Mincho ProN",
        "Hiragino Sans",
        "Hiragino Sans GB",
        "Hoefler Text",
        "Impact",
        "InaiMathi",
        "ITF Devanagari",
        "Kailasa",
        "Kannada MN",
        "Kannada Sangam MN",
        "Kefa",
        "Keyboard",
        "Khmer MN",
        "Khmer Sangam MN",
        "Kohinoor Bangla",
        "Kohinoor Devanagari",
        "Kohinoor Gujarati",
        "Kohinoor Telugu",
        "Lao MN",
        "Lao Sangam MN",
        "LastResort",
        "Lucida Grande",
        "Luminari",
        "Marker Felt",
        "Menlo",
        "Monaco",
        "MuktaMahee",
        "Myanmar MN",
        "Myanmar Sangam MN",
        "New Peninim MT",
        "New York",
        "Noteworthy",
        "Optima",
        "Palatino",
        "Papyrus",
        "Party LET",
        "Phosphate",
        "PingFang HK",
        "PingFang SC",
        "PingFang TC",
        "PT Mono",
        "PT Sans",
        "PT Sans Caption",
        "PT Sans Narrow",
        "Raanana",
        "Rockwell",
        "Sathu",
        "Savoye LET",
        "SignPainter",
        "Silom",
        "Sinhala MN",
        "Sinhala Sangam MN",
        "Skia",
        "Snell Roundhand",
        "Songti SC",
        "Songti TC",
        "STHeiti",
        "STSong",
        "STIX Two Math",
        "STIX Two Text",
        "Symbol",
        "Tamil MN",
        "Tamil Sangam MN",
        "Telugu MN",
        "Telugu Sangam MN",
        "Thonburi",
        "Times",
        "Waseem",
        "Webdings",
        "Wingdings",
        "Zapf Dingbats",
        "Zapfino",
    ),
    WINDOWS: (
        "Arial",
        "Times New Roman",
        "Courier New",
        "Verdana",
        "Georgia",
        "Trebuchet MS",
        "Tahoma",
        "Segoe UI",
        "Segoe UI Emoji",
        "Segoe MDL2 Assets",
        "Segoe Fluent Icons",
        "Calibri",
        "Cambria",
        "Cambria Math",
        "Candara",
        "Nirmala UI",
        "Consolas",
        "Constantia",
        "Corbel",
        "Ebrima",
        "Gadugi",
        "Javanese Text",
        "Leelawadee UI",
        "Malgun Gothic",
        "Microsoft JhengHei",
        "Microsoft YaHei",
        "Myanmar Text",
        "Segoe Print",
        "Segoe Script",
        "Segoe UI Historic",
        "Segoe UI Symbol",
        "Sitka",
        "Yu Gothic",
        "Bahnschrift",
        "HoloLens MDL2 Assets",
    ),
    LINUX: (
        "Arimo",
        "Cousine",
        "Tinos",
        "Twemoji Mozilla",
        "Cantarell",
        "DejaVu Sans",
        "DejaVu Sans Mono",
        "DejaVu Serif",
        "Liberation Mono",
        "Liberation Sans",
        "Liberation Serif",
        "Noto Color Emoji",
        "Noto Sans Devanagari",
        "Noto Sans JP",
        "Noto Sans KR",
        "Noto Sans SC",
        "Noto Sans TC",
    ),
}


def font_definitions_for_target_os(target_os: TargetOS) -> tuple[Font, ...]:
    return tuple(font for font in _FONT_DEFINITIONS if target_os in font.target_os)


def marker_families_for_target_os(target_os: TargetOS) -> tuple[str, ...]:
    return tuple(font.family for font in font_definitions_for_target_os(target_os) if font.marker)


def blocked_families_for_target_os(target_os: TargetOS) -> frozenset[str]:
    return frozenset(
        font.family
        for font in _FONT_DEFINITIONS
        if target_os not in font.target_os and font.leak_signal
    )


def default_families_for_target_os(target_os: TargetOS) -> frozenset[str]:
    """
    Return the curated baseline families for a claimed OS.

    Host adapters keep this platform baseline present, then sample locally
    discovered non-baseline fonts as extras.
    """
    return frozenset(_DEFAULT_FONT_FAMILIES.get(target_os, ()))


def essential_families_for_target_os(target_os: TargetOS) -> frozenset[str]:
    """
    Return baseline families that should survive aggressive per-context subsetting.

    These are the fonts Camoufox treats as the minimum plausible core for a
    claimed OS. Adapters can still expose additional families, but they should
    keep this baseline present so generic-family fallbacks and OS marker checks
    continue to behave like a real install.
    """
    return default_families_for_target_os(target_os)
