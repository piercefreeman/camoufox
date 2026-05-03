from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .common import LINUX, MACOS, WINDOWS, TargetOS, empty_target_os_set, target_os_set


@dataclass(frozen=True)
class Voice:
    """
    Catalog entry for a spoofable speech-synthesis voice.

    `target_os` is the set of OS identities this voice legitimately belongs to.
    `bundled` marks voices that are considered baseline OS inventory rather than
    optional extras.
    `marker` marks high-signal voices that can help confirm the claimed OS when
    they are locally available.
    `leak_signal` marks voices that should be denied when sampling for a
    different target OS; `blocked_voice_names_for_target_os()` builds that
    denylist and `HostFingerprintAdapter.sample_voices()` enforces it.
    """
    name: str
    aliases: tuple[str, ...] = ()
    target_os: frozenset[TargetOS] = field(default_factory=empty_target_os_set)

    # Bundled voices are treated as baseline host inventory and sampled first.
    bundled: bool = False

    # Marker voices are re-added after random sampling when the local host has
    # them, so the emitted profile retains expected OS-ID signals.
    marker: bool = False

    # Leak-signal voices are excluded from profiles for other target OSes.
    # This is only consulted during final sampling, not during host probing.
    leak_signal: bool = False

    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


_VOICE_DEFINITIONS: tuple[Voice, ...] = (
    Voice("Alex", target_os=target_os_set(MACOS), bundled=True, marker=True, leak_signal=True),
    Voice("Samantha", target_os=target_os_set(MACOS), bundled=True, marker=True, leak_signal=True),
    Voice("Victoria", target_os=target_os_set(MACOS), bundled=True, marker=True, leak_signal=True),
    Voice("Karen", target_os=target_os_set(MACOS), bundled=True, marker=True, leak_signal=True),
    Voice("Daniel", target_os=target_os_set(MACOS), bundled=True, leak_signal=True),
    Voice("Fred", target_os=target_os_set(MACOS), bundled=True, marker=True, leak_signal=True),
    Voice(
        "Microsoft David - English (United States)",
        target_os=target_os_set(WINDOWS),
        bundled=True,
        marker=True,
        leak_signal=True,
    ),
    Voice(
        "Microsoft Zira - English (United States)",
        target_os=target_os_set(WINDOWS),
        bundled=True,
        marker=True,
        leak_signal=True,
    ),
    Voice(
        "Microsoft Mark - English (United States)",
        target_os=target_os_set(WINDOWS),
        bundled=True,
        marker=True,
        leak_signal=True,
    ),
    Voice("English", target_os=target_os_set(LINUX), bundled=True),
    Voice("English-us", target_os=target_os_set(LINUX), bundled=True),
    Voice("German", target_os=target_os_set(LINUX), bundled=True),
    Voice("French", target_os=target_os_set(LINUX), bundled=True),
    Voice("Spanish", target_os=target_os_set(LINUX), bundled=True),
)


def voice_definitions_for_target_os(target_os: TargetOS) -> tuple[Voice, ...]:
    return tuple(voice for voice in _VOICE_DEFINITIONS if target_os in voice.target_os)


def marker_voice_names_for_target_os(target_os: TargetOS) -> tuple[str, ...]:
    return tuple(voice.name for voice in voice_definitions_for_target_os(target_os) if voice.marker)


def blocked_voice_names_for_target_os(target_os: TargetOS) -> frozenset[str]:
    return frozenset(
        voice.name
        for voice in _VOICE_DEFINITIONS
        if target_os not in voice.target_os and voice.leak_signal
    )


def dedupe_voices(voices: Iterable[Voice]) -> tuple[Voice, ...]:
    """
    Preserve first-seen voices while deduplicating by canonical voice name.
    """
    seen: dict[str, Voice] = {}
    for voice in voices:
        seen.setdefault(voice.name, voice)
    return tuple(seen.values())
