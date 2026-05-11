from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal, TypedDict

from .dom_serializer import DOMElement, DOMSnapshot

ACTION_FULL_REFRESH_THRESHOLD = 0.75

ActionChangeStatus = Literal["full_refresh", "same_page"]


class ActionChangePayload(TypedDict):
    status: ActionChangeStatus
    full_refresh: bool
    navigated: bool
    element_change_ratio: float
    element_change_threshold: float
    before_count: int
    after_count: int
    added_count: int
    removed_count: int
    added: list[str]
    removed: list[str]
    new_page_count: int


@dataclass(frozen=True, slots=True)
class ActionChange:
    status: ActionChangeStatus
    full_refresh: bool
    navigated: bool
    element_change_ratio: float
    element_change_threshold: float
    before_count: int
    after_count: int
    added_count: int
    removed_count: int
    added: tuple[str, ...]
    removed: tuple[str, ...]
    new_page_count: int = 0

    def to_payload(self) -> ActionChangePayload:
        return {
            "status": self.status,
            "full_refresh": self.full_refresh,
            "navigated": self.navigated,
            "element_change_ratio": self.element_change_ratio,
            "element_change_threshold": self.element_change_threshold,
            "before_count": self.before_count,
            "after_count": self.after_count,
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "added": list(self.added),
            "removed": list(self.removed),
            "new_page_count": self.new_page_count,
        }


@dataclass(frozen=True, slots=True)
class DomDiff:
    before_items: tuple[DOMElement, ...]
    after_items: tuple[DOMElement, ...]
    before_url: str
    after_url: str
    new_page_count: int = 0
    full_refresh_threshold: float = ACTION_FULL_REFRESH_THRESHOLD

    @classmethod
    def from_snapshots(
        cls,
        before_snapshot: DOMSnapshot | None,
        after_snapshot: DOMSnapshot | None,
        *,
        before_url: str,
        after_url: str,
        new_page_count: int = 0,
    ) -> DomDiff:
        return cls(
            before_items=tuple(before_snapshot.items) if before_snapshot else (),
            after_items=tuple(after_snapshot.items) if after_snapshot else (),
            before_url=before_url,
            after_url=after_url,
            new_page_count=new_page_count,
        )

    def action_change(self) -> ActionChange:
        element_change_ratio = self.element_change_ratio()
        navigated = self._navigation_identity(self.before_url) != self._navigation_identity(self.after_url)
        full_refresh = navigated or element_change_ratio > self.full_refresh_threshold
        added, removed = self.element_delta()

        return ActionChange(
            status="full_refresh" if full_refresh else "same_page",
            full_refresh=full_refresh,
            navigated=navigated,
            element_change_ratio=round(element_change_ratio, 4),
            element_change_threshold=self.full_refresh_threshold,
            before_count=len(self.before_items),
            after_count=len(self.after_items),
            added_count=len(added),
            removed_count=len(removed),
            added=() if full_refresh else added,
            removed=() if full_refresh else removed,
            new_page_count=self.new_page_count,
        )

    def element_change_ratio(self) -> float:
        total = max(len(self.before_items), len(self.after_items))
        if total == 0:
            return 0.0
        before_counts = self._signature_counts(self.before_items)
        after_counts = self._signature_counts(self.after_items)
        unchanged = sum((before_counts & after_counts).values())
        return max(0.0, min(1.0, 1.0 - (unchanged / total)))

    def element_delta(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        before_counts = self._signature_counts(self.before_items)
        after_counts = self._signature_counts(self.after_items)
        added_counts = after_counts - before_counts
        removed_counts = before_counts - after_counts
        return self._lines_for_counts(self.after_items, added_counts), self._lines_for_counts(
            self.before_items,
            removed_counts,
        )

    @classmethod
    def _signature_counts(cls, items: tuple[DOMElement, ...]) -> Counter[str]:
        return Counter(cls._element_signature(item) for item in items)

    @classmethod
    def _lines_for_counts(cls, items: tuple[DOMElement, ...], counts: Counter[str]) -> tuple[str, ...]:
        remaining = Counter(counts)
        lines: list[str] = []
        for item in items:
            signature = cls._element_signature(item)
            if remaining[signature] <= 0:
                continue
            lines.append(item.agent_line())
            remaining[signature] -= 1
        return tuple(lines)

    @staticmethod
    def _element_signature(item: DOMElement) -> str:
        line = item.agent_line()
        return line.split("] - ", 1)[1] if "] - " in line else line

    @staticmethod
    def _navigation_identity(url: str) -> str:
        return str(url or "").split("#", 1)[0]


def build_action_change(
    before_snapshot: DOMSnapshot | None,
    after_snapshot: DOMSnapshot | None,
    *,
    before_url: str,
    after_url: str,
    new_page_count: int = 0,
) -> ActionChange:
    return DomDiff.from_snapshots(
        before_snapshot,
        after_snapshot,
        before_url=before_url,
        after_url=after_url,
        new_page_count=new_page_count,
    ).action_change()


def render_action_change(change: ActionChange) -> str:
    if change.full_refresh:
        reasons: list[str] = []
        if change.navigated:
            reasons.append("navigation")
        ratio = change.element_change_ratio
        threshold = change.element_change_threshold
        if ratio > threshold:
            reasons.append(f"{ratio:.0%} elements changed")
        if change.new_page_count:
            reasons.append(_count_label(change.new_page_count, "new page"))
        suffix = f" ({', '.join(reasons)})" if reasons else ""
        return f"page: full refresh{suffix}"

    added = list(change.added)
    removed = list(change.removed)
    if not added and not removed:
        lines = ["page: stayed the same"]
        if change.new_page_count:
            lines[0] += f" ({_count_label(change.new_page_count, 'new page')})"
        return "\n".join(lines)

    counts = []
    counts.append(_count_label(len(added), "added"))
    counts.append(_count_label(len(removed), "removed"))
    if change.new_page_count:
        counts.append(_count_label(change.new_page_count, "new page"))

    lines = [f"page: mostly unchanged ({', '.join(counts)})"]
    lines.extend(f"+ {line}" for line in added)
    lines.extend(f"- {line}" for line in removed)
    return "\n".join(lines)


def _count_label(count: int, label: str) -> str:
    return f"{count} {label}{'' if count == 1 else 's'}"
