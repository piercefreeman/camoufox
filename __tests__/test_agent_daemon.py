from __future__ import annotations

from http.server import HTTPServer
from socketserver import ThreadingMixIn

from click.testing import CliRunner
from rotunda import __main__ as cli_module
from rotunda.__main__ import cli
from rotunda.agent import store as store_module
from rotunda.agent.daemon import AgentDaemon, AgentHTTPServer
from rotunda.agent.store import AgentStore


def isolate_agent_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store_module, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(store_module, "RESOURCES_FILE", tmp_path / "resources.json")
    monkeypatch.setattr(store_module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(
        store_module,
        "ensure_agent_dirs",
        lambda: (tmp_path / "sessions").mkdir(parents=True, exist_ok=True),
    )


def test_agent_http_server_is_single_threaded_for_playwright_sync_api() -> None:
    assert issubclass(AgentHTTPServer, HTTPServer)
    assert not issubclass(AgentHTTPServer, ThreadingMixIn)


def test_agent_profile_defaults_to_headed(tmp_path, monkeypatch) -> None:
    isolate_agent_store(tmp_path, monkeypatch)

    profile = AgentStore().create_profile(name="headed")

    assert profile["headless"] is False
    assert profile["humanize"] is True


def test_agent_store_can_refresh_page_element_resources(tmp_path, monkeypatch) -> None:
    isolate_agent_store(tmp_path, monkeypatch)
    store = AgentStore()
    page = store.register(kind="page", id="page_1", profile_id="prof_1", parent_id="ctx_1")
    store.register(kind="element", id="old", profile_id="prof_1", parent_id=page.id)
    store.register(kind="element", id="other", profile_id="prof_1", parent_id="page_2")

    store.remove_children(page.id, kind="element")

    resources = store.list_resources()
    assert [resource.id for resource in resources] == ["page_1", "other"]


def test_agent_click_fill_and_type_accept_global_element_refs(tmp_path, monkeypatch) -> None:
    isolate_agent_store(tmp_path, monkeypatch)
    store = AgentStore()
    page = store.register(kind="page", id="page_1", profile_id="prof_1", parent_id="ctx_1")
    store.register(kind="element", id="button_ref", profile_id="prof_1", parent_id=page.id)

    click_page, click_ref = cli_module._agent_target_from_click_args(store, ("button_ref",))
    fill_page, fill_ref, text = cli_module._agent_target_from_text_args(
        store,
        ("button_ref", "hello"),
        command_name="fill",
    )

    assert click_page.id == page.id
    assert click_ref == "button_ref"
    assert fill_page.id == page.id
    assert fill_ref == "button_ref"
    assert text == "hello"

    type_page, type_ref, typed_text = cli_module._agent_target_from_text_args(
        store,
        ("button_ref", "typed"),
        command_name="type",
    )

    assert type_page.id == page.id
    assert type_ref == "button_ref"
    assert typed_text == "typed"

    select_page, select_ref, values = cli_module._agent_target_from_values_args(
        store,
        ("button_ref", "one", "two"),
        command_name="select",
    )

    assert select_page.id == page.id
    assert select_ref == "button_ref"
    assert values == ["one", "two"]


class FakeKeyboard:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    def insert_text(self, text: str) -> None:
        self.events.append(("insert_text", text))


class FakePage:
    def __init__(self, events: list[tuple]) -> None:
        self.keyboard = FakeKeyboard(events)


class FakeLocator:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    def click(self, *, timeout: int) -> None:
        self.events.append(("click", timeout))

    def press(self, key: str, *, timeout: int | None = None) -> None:
        self.events.append(("press", key, timeout))

    def evaluate(self, script: str) -> dict:
        self.events.append(("evaluate", script))
        return {
            "tag": "select",
            "role": "",
            "name": "Country",
            "text": "United States Canada",
            "attributes": {"id": "country"},
            "state": {"visible": True, "disabled": False},
            "value": "us",
            "bounds": {"x": 1, "y": 2, "width": 100, "height": 20},
            "selectedIndex": 0,
            "selectedValues": ["us"],
            "options": [
                {
                    "index": 0,
                    "value": "us",
                    "label": "United States",
                    "text": "United States",
                    "selected": True,
                    "disabled": False,
                },
                {
                    "index": 1,
                    "value": "ca",
                    "label": "Canada",
                    "text": "Canada",
                    "selected": False,
                    "disabled": False,
                },
            ],
            "outerHTML": '<select id="country"></select>',
        }

    def select_option(
        self,
        value: str | list[str] | None = None,
        *,
        index: int | list[int] | None = None,
        label: str | list[str] | None = None,
        timeout: int,
    ) -> list[str]:
        self.events.append(("select_option", value, index, label, timeout))
        if value is not None:
            return [value] if isinstance(value, str) else value
        if label is not None:
            return [label] if isinstance(label, str) else label
        if index is not None:
            indexes = [index] if isinstance(index, int) else index
            return [str(item) for item in indexes]
        return []


class FakeSerializer:
    def __init__(self, locator: FakeLocator) -> None:
        self.locator = locator

    def resolve_locator(self, page: FakePage, ref: str) -> FakeLocator:
        return self.locator

    def get_reference(self, ref: str):
        class Element:
            frame_index = 0
            frame_url = "https://example.test"
            frame_name = ""

        class Reference:
            element = Element()

        return Reference()


def test_agent_fill_uses_rotunda_insert_text_path() -> None:
    events: list[tuple] = []
    daemon = AgentDaemon({"id": "prof_1"})
    daemon.pages["page_1"] = FakePage(events)
    daemon.page_serializers["page_1"] = FakeSerializer(FakeLocator(events))
    daemon.describe_page = lambda page_id: {"page": {"id": page_id}}

    daemon.fill_text("page_1", "input_ref", "hello", submit=True)

    assert events == [
        ("click", 15_000),
        ("press", "ControlOrMeta+A", 15_000),
        ("press", "Backspace", 15_000),
        ("insert_text", "hello"),
        ("press", "Enter", None),
    ]


def test_agent_type_uses_rotunda_insert_text_path() -> None:
    events: list[tuple] = []
    daemon = AgentDaemon({"id": "prof_1"})
    daemon.pages["page_1"] = FakePage(events)
    daemon.page_serializers["page_1"] = FakeSerializer(FakeLocator(events))
    daemon.describe_page = lambda page_id: {"page": {"id": page_id}}

    daemon.type_text("page_1", "input_ref", "hello", submit=True)

    assert events == [
        ("click", 15_000),
        ("insert_text", "hello"),
        ("press", "Enter", None),
    ]


def test_agent_info_includes_select_options() -> None:
    events: list[tuple] = []
    daemon = AgentDaemon({"id": "prof_1"})
    daemon.pages["page_1"] = FakePage(events)
    daemon.page_serializers["page_1"] = FakeSerializer(FakeLocator(events))
    daemon._page_payload = lambda page_id, page: {"id": page_id, "url": "https://example.test"}

    result = daemon.element_info("page_1", "select_ref")

    assert result["info"]["options"][1]["value"] == "ca"
    assert "value='ca'" in result["text"]
    assert "selectedValues: [\"us\"]" in result["text"]


def test_agent_select_can_match_by_value_label_or_index() -> None:
    events: list[tuple] = []
    daemon = AgentDaemon({"id": "prof_1"})
    daemon.pages["page_1"] = FakePage(events)
    daemon.page_serializers["page_1"] = FakeSerializer(FakeLocator(events))
    daemon.describe_page = lambda page_id: {"page": {"id": page_id}}

    by_value = daemon.select_options("page_1", "select_ref", ["ca"])
    by_label = daemon.select_options("page_1", "select_ref", ["Canada"], by="label")
    by_index = daemon.select_options("page_1", "select_ref", ["1"], by="index")

    assert by_value["selected"] == ["ca"]
    assert by_label["selected"] == ["Canada"]
    assert by_index["selected"] == ["1"]
    assert events == [
        ("select_option", "ca", None, None, 15_000),
        ("select_option", None, None, "Canada", 15_000),
        ("select_option", None, 1, None, 15_000),
    ]


def test_agent_help_exposes_describe_not_list() -> None:
    result = CliRunner().invoke(cli, ["agent", "--help"])

    assert result.exit_code == 0
    assert "describe" in result.output
    assert "fill" in result.output
    assert "info" in result.output
    assert "select" in result.output
    assert "type" in result.output
    assert " list " not in result.output
    assert " enter " not in result.output


def test_agent_action_help_explains_positional_arguments() -> None:
    for command in ("click", "info", "fill", "select", "type"):
        result = CliRunner().invoke(cli, ["agent", command, "--help"])

        assert result.exit_code == 0
        assert "Arguments:" in result.output
        assert "REF" in result.output
        assert "PAGE" in result.output
