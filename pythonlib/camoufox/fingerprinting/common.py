from __future__ import annotations

from typing import Final, Literal, TypeAlias

MACOS: Final[Literal["macos"]] = "macos"
LINUX: Final[Literal["linux"]] = "linux"
WINDOWS: Final[Literal["windows"]] = "windows"

TargetOS: TypeAlias = Literal["macos", "linux", "windows"]
HostTargetOS: TypeAlias = Literal["macos", "linux"]

TARGET_OSES: Final[tuple[TargetOS, ...]] = (MACOS, LINUX, WINDOWS)
HOST_TARGET_OSES: Final[tuple[HostTargetOS, ...]] = (MACOS, LINUX)


def empty_target_os_set() -> frozenset[TargetOS]:
    return frozenset()


def target_os_set(*values: TargetOS) -> frozenset[TargetOS]:
    return frozenset(values)
