"""Small immutable records shared by the cadence training pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MouseStep:
    dt_ms: float
    x: float
    y: float
    action: str


@dataclass(frozen=True)
class MouseEpisode:
    source: str
    start_x: float
    start_y: float
    dst_x: float
    dst_y: float
    steps: tuple[MouseStep, ...]


@dataclass(frozen=True)
class KeyStep:
    dt_ms: float
    action: str


@dataclass(frozen=True)
class KeyboardEditStep:
    action: str
    step_kind: str


@dataclass(frozen=True)
class KeyboardEpisode:
    source: str
    final_string: str
    steps: tuple[KeyStep, ...]
    initial_string: str = ""


@dataclass(frozen=True)
class FocusedTextSnapshot:
    source: str
    offset_ms: int
    trigger_offset_ms: int | None
    identity: str
    raw_accessibility_id: str | None
    value: str

    @property
    def effective_offset_ms(self) -> int:
        return self.trigger_offset_ms if self.trigger_offset_ms is not None else self.offset_ms


@dataclass(frozen=True)
class KeyDef:
    token: str
    x: float
    y: float


@dataclass(frozen=True)
class WandbState:
    module: Any
    run: Any
    owns_run: bool
