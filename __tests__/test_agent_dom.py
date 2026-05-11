from __future__ import annotations

from rotunda.agent.dom import (
    ActionChange,
    DomDiff,
    build_action_change,
    render_action_change,
)
from rotunda.agent.dom_serializer import DOMElement, DOMFrame, DOMSnapshot


def _action_item(ref: str, name: str, *, role: str = "button") -> DOMElement:
    return DOMElement(
        ref=ref,
        uuid=ref,
        frame_index=0,
        frame_url="https://example.test",
        frame_name="",
        local_id=0,
        tag="button",
        role=role,
        name=name,
        text=name,
        attributes={},
        xpath=f"/html/body/button[{ref}]",
        css=f"css=button#{ref}",
        in_shadow_tree=False,
        interactive=True,
        content=False,
        disabled=False,
        bounds=None,
        depth=1,
    )


def _action_snapshot(*items: DOMElement) -> DOMSnapshot:
    return DOMSnapshot(
        items=list(items),
        frames=[DOMFrame(index=0, url="https://example.test")],
        text="\n".join(item.agent_line() for item in items),
    )


def test_dom_diff_renders_same_page_delta_without_unchanged_elements() -> None:
    before = _action_snapshot(_action_item("old_save", "Save"), _action_item("old_cancel", "Cancel"))
    after = _action_snapshot(_action_item("new_save", "Save"), _action_item("new_done", "Done"))

    diff = DomDiff.from_snapshots(
        before,
        after,
        before_url="https://example.test/form",
        after_url="https://example.test/form",
    )
    change = diff.action_change()
    text = render_action_change(change)

    assert diff.element_change_ratio() == 0.5
    assert isinstance(change, ActionChange)
    assert change.status == "same_page"
    assert change.added == ('[new_done] - button "Done"',)
    assert change.removed == ('[old_cancel] - button "Cancel"',)
    assert change.to_payload()["added"] == ['[new_done] - button "Done"']
    assert text == (
        "page: mostly unchanged (1 added, 1 removed)\n"
        '+ [new_done] - button "Done"\n'
        '- [old_cancel] - button "Cancel"'
    )
    assert "Save" not in text


def test_dom_diff_reports_identical_elements_as_same_page() -> None:
    before = _action_snapshot(_action_item("old_save", "Save"), _action_item("old_cancel", "Cancel"))
    after = _action_snapshot(_action_item("new_save", "Save"), _action_item("new_cancel", "Cancel"))

    change = build_action_change(
        before,
        after,
        before_url="https://example.test/form",
        after_url="https://example.test/form",
    )

    assert change.status == "same_page"
    assert change.added == ()
    assert change.removed == ()
    assert render_action_change(change) == "page: stayed the same"


def test_dom_diff_reports_full_refresh_without_full_delta() -> None:
    before = _action_snapshot(
        _action_item("old_a", "Alpha"),
        _action_item("old_b", "Beta"),
        _action_item("old_c", "Gamma"),
        _action_item("old_d", "Delta"),
    )
    after = _action_snapshot(
        _action_item("new_a", "One"),
        _action_item("new_b", "Two"),
        _action_item("new_c", "Three"),
        _action_item("new_d", "Four"),
    )

    change = build_action_change(
        before,
        after,
        before_url="https://example.test/start",
        after_url="https://example.test/next",
    )

    assert change.status == "full_refresh"
    assert change.added == ()
    assert change.removed == ()
    assert change.to_payload()["removed"] == []
    assert render_action_change(change) == "page: full refresh (navigation, 100% elements changed)"
