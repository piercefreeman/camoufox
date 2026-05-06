from __future__ import annotations

import pytest
from rotunda.agent import DOMSerializer
from rotunda.agent.dom_serializer import DOM_SERIALIZER_SCRIPT


class FakeLocator:
    def __init__(
        self,
        count: int,
        *,
        visible: bool = True,
        visible_indexes: set[int] | None = None,
        index: int | None = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._visible_indexes = visible_indexes
        self.index = index

    def count(self) -> int:
        return self._count

    @property
    def first(self) -> FakeLocator:
        return self

    def nth(self, index: int) -> FakeLocator:
        if self._visible_indexes is None:
            visible = self._visible
        else:
            visible = index in self._visible_indexes
        return FakeLocator(1, visible=visible, index=index)

    def is_visible(self) -> bool:
        return self._visible

    def element_handle(self, *, timeout: float | None = None) -> FakeLocator:
        return self


class FakeFrame:
    def __init__(
        self,
        url: str,
        items: list[dict],
        *,
        name: str = "",
        visible_indexes: set[int] | None = None,
    ) -> None:
        self.url = url
        self.name = name
        self.parent_frame = None
        self.items = items
        self.selectors: list[str] = []
        self.visible_indexes = visible_indexes

    def evaluate(self, script: str, options: dict) -> list[dict]:
        assert script == DOM_SERIALIZER_SCRIPT
        assert options["includeContent"] is True
        assert options["includeInteractive"] is True
        return self.items

    def locator(self, selector: str) -> FakeLocator:
        self.selectors.append(selector)
        if selector not in {self.items[0]["css"], f"xpath={self.items[0]['xpath']}"}:
            return FakeLocator(0)
        count = 1 if self.visible_indexes is None else len(self.visible_indexes) + 1
        return FakeLocator(count, visible_indexes=self.visible_indexes)


class FakePage:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self.frames = frames


def raw_button(*, xpath: str, css: str = "css=button#login") -> dict:
    return {
        "local_id": 0,
        "tag": "button",
        "role": "button",
        "name": "Log in",
        "text": "Log in",
        "attributes": {"id": "login", "type": "submit"},
        "xpath": xpath,
        "css": css,
        "shadow": False,
        "interactive": True,
        "content": False,
        "disabled": False,
        "bounds": {"x": 10, "y": 20, "width": 80, "height": 30},
        "depth": 3,
    }


def test_serialize_renders_compact_agent_lines_for_all_frames() -> None:
    main = FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])
    child = FakeFrame(
        "https://auth.example.com",
        [
            {
                **raw_button(xpath="/html/body/form/button[1]", css="css=button#submit"),
                "local_id": 1,
                "name": "Submit",
                "text": "Submit",
                "attributes": {"id": "submit"},
            }
        ],
        name="login-frame",
    )
    child.parent_frame = main
    serializer = DOMSerializer(hash_length=6)

    snapshot = serializer.serialize(FakePage([main, child]))

    assert len(snapshot.items) == 2
    assert snapshot.frames[1].parent_index == 0
    assert "Frame 0: https://example.com" in snapshot.text
    assert 'Frame 1 "login-frame": https://auth.example.com' in snapshot.text
    assert 'button "Log in"' in snapshot.text
    assert 'button "Submit"' in snapshot.text
    assert snapshot.items[0].ref != snapshot.items[1].ref


def test_stable_ref_survives_selector_changes_for_same_semantic_element() -> None:
    serializer = DOMSerializer(hash_length=6)
    first = serializer.serialize(
        FakePage([FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])])
    )
    second = serializer.serialize(
        FakePage(
            [
                FakeFrame(
                    "https://example.com",
                    [raw_button(xpath="/html/body/main/div/button[1]")],
                )
            ]
        )
    )

    assert first.items[0].ref == second.items[0].ref


def test_resolve_locator_uses_in_memory_reference_selectors() -> None:
    frame = FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])
    page = FakePage([frame])
    serializer = DOMSerializer(hash_length=6)
    snapshot = serializer.serialize(page)

    locator = serializer.resolve_locator(page, snapshot.items[0].ref)

    assert isinstance(locator, FakeLocator)
    assert frame.selectors == ["xpath=/html/body/button[1]"]


def test_resolve_locator_matches_frame_url_before_falling_back_to_index() -> None:
    original = FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])
    serializer = DOMSerializer(hash_length=6)
    snapshot = serializer.serialize(FakePage([original]))

    other = FakeFrame("https://other.example.com", [raw_button(xpath="/html/body/button[1]")])
    moved = FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])
    locator = serializer.resolve_locator(FakePage([other, moved]), snapshot.items[0].ref)

    assert isinstance(locator, FakeLocator)
    assert other.selectors == []
    assert moved.selectors == []


def test_resolve_locator_prefers_visible_match_for_selector() -> None:
    frame = FakeFrame(
        "https://example.com",
        [raw_button(xpath="/html/body/button[1]")],
        visible_indexes={1},
    )
    serializer = DOMSerializer(hash_length=6)
    snapshot = serializer.serialize(FakePage([frame]))

    locator = serializer.resolve_locator(FakePage([frame]), snapshot.items[0].ref)

    assert isinstance(locator, FakeLocator)
    assert locator.index == 1


def test_resolve_locator_uses_captured_handle_before_selectors() -> None:
    frame = FakeFrame("https://example.com", [raw_button(xpath="/html/body/button[1]")])
    serializer = DOMSerializer(hash_length=6)
    snapshot = serializer.serialize(FakePage([frame]))
    frame.selectors.clear()

    locator = serializer.resolve_locator(FakePage([frame]), snapshot.items[0].ref)

    assert isinstance(locator, FakeLocator)
    assert frame.selectors == []


def test_unknown_reference_raises_key_error() -> None:
    serializer = DOMSerializer()

    with pytest.raises(KeyError, match="Unknown DOM reference"):
        serializer.get_reference("missing")
