"""Small immutable records shared by the cadence training pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScreenSizeFilter:
    """Laptop-like screen bounds used to accept or reject recorder events."""

    enabled: bool = True
    min_width: int = 1100
    max_width: int = 1920
    min_height: int = 700
    max_height: int = 1300
    min_aspect_ratio: float = 1.2
    max_aspect_ratio: float = 2.2
    require_known: bool = True

    def matches(self, width: int, height: int) -> bool:
        """Return whether a concrete screen size looks like an allowed device."""
        if not self.enabled:
            return True
        if width <= 0 or height <= 0:
            return False
        # Normalize orientation so callers can pass either portrait or landscape
        # dimensions while the filter still describes the physical display.
        long_edge = max(width, height)
        short_edge = min(width, height)
        aspect_ratio = long_edge / short_edge
        return (
            self.min_width <= long_edge <= self.max_width
            and self.min_height <= short_edge <= self.max_height
            and self.min_aspect_ratio <= aspect_ratio <= self.max_aspect_ratio
        )

    def allows(self, screen_size: tuple[int, int] | None) -> bool:
        """Apply the filter to an optional screen size from an event stream."""
        if not self.enabled:
            return True
        if screen_size is None:
            return not self.require_known
        return self.matches(*screen_size)


@dataclass(frozen=True)
class MouseStep:
    """One timed mouse movement or click inside a reconstructed episode."""

    dt_ms: float
    x: float
    y: float
    action: str


@dataclass(frozen=True)
class MouseEpisode:
    """A motivated pointer path from a resting start position to a click."""

    source: str
    start_x: float
    start_y: float
    dst_x: float
    dst_y: float
    steps: tuple[MouseStep, ...]


@dataclass(frozen=True)
class KeyStep:
    """One timed keyboard action in a reconstructed edit sequence."""

    dt_ms: float
    action: str


@dataclass(frozen=True)
class KeyboardEpisode:
    """A text edit episode that turns an initial string into a final string."""

    source: str
    final_string: str
    steps: tuple[KeyStep, ...]
    initial_string: str = ""


@dataclass(frozen=True)
class FocusedTextSnapshot:
    """Focused accessibility text value captured at a recorder timestamp."""

    source: str
    offset_ms: int
    trigger_offset_ms: int | None
    identity: str
    raw_accessibility_id: str | None
    value: str
    key_action: str | None = None
    key_code: int | None = None
    is_keyboard_event: bool = False

    @property
    def effective_offset_ms(self) -> int:
        """Use trigger time when present so debounced snapshots sort by cause."""
        return self.trigger_offset_ms if self.trigger_offset_ms is not None else self.offset_ms


@dataclass(frozen=True)
class KeyDef:
    """Keyboard geometry anchor for a token on the normalized layout."""

    token: str
    x: float
    y: float


@dataclass(frozen=True)
class WandbState:
    """Active W&B module/run pair plus ownership for safe cleanup."""

    module: Any
    run: Any
    owns_run: bool
