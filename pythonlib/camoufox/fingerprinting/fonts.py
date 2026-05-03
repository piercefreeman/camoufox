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
