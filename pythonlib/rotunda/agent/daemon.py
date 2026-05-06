from __future__ import annotations

import json
import os
import signal
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal, cast

import rich_click as click
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .dom_serializer import DOMSerializer
from .store import AgentStore

ELEMENT_INFO_SCRIPT = r"""
(el) => {
  const clean = (value) => value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  const attrs = {};
  for (const attr of Array.from(el.attributes || [])) {
    attrs[attr.name] = attr.value;
  }
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  const rects = Array.from(el.getClientRects());
  const visible = style.display !== "none" &&
    style.visibility !== "hidden" &&
    style.visibility !== "collapse" &&
    Number(style.opacity) !== 0 &&
    rects.some((rect) => rect.width > 0 && rect.height > 0);

  const info = {
    tag: el.tagName.toLowerCase(),
    role: clean(el.getAttribute("role")),
    name: clean(el.getAttribute("aria-label") || el.getAttribute("name") || ""),
    text: clean(el.innerText || el.textContent || ""),
    attributes: attrs,
    state: {
      visible,
      disabled: Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true",
      readonly: Boolean(el.readOnly),
      required: Boolean(el.required),
      checked: Boolean(el.checked),
      multiple: Boolean(el.multiple),
      contentEditable: Boolean(el.isContentEditable),
    },
    value: "value" in el ? el.value : null,
    bounds: {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    outerHTML: el.outerHTML || "",
  };

  if (el instanceof HTMLSelectElement) {
    info.selectedIndex = el.selectedIndex;
    info.selectedValues = Array.from(el.selectedOptions).map((option) => option.value);
    info.options = Array.from(el.options).map((option, index) => ({
      index,
      value: option.value,
      label: option.label,
      text: clean(option.text),
      selected: option.selected,
      disabled: option.disabled,
    }));
  }

  return info;
}
"""

EXTRACT_LINKS_SCRIPT = r"""
() => {
  const clean = (value) => value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rects = Array.from(el.getClientRects());
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 &&
      rects.some((rect) => rect.width > 0 && rect.height > 0);
  };
  return Array.from(document.querySelectorAll("a[href]"))
    .filter(visible)
    .map((link) => ({
      text: clean(link.innerText || link.textContent),
      href: link.href,
      title: clean(link.getAttribute("title")),
      target: clean(link.getAttribute("target")),
    }));
}
"""

EXTRACT_FORMS_SCRIPT = r"""
() => {
  const clean = (value) => value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  const fieldPayload = (field) => ({
    tag: field.tagName.toLowerCase(),
    type: clean(field.getAttribute("type")),
    name: clean(field.getAttribute("name")),
    id: clean(field.getAttribute("id")),
    label: clean(field.labels ? Array.from(field.labels).map((label) => label.innerText).join(" ") : ""),
    placeholder: clean(field.getAttribute("placeholder")),
    value: "value" in field ? field.value : "",
    checked: Boolean(field.checked),
    disabled: Boolean(field.disabled) || field.getAttribute("aria-disabled") === "true",
    required: Boolean(field.required),
  });
  return Array.from(document.forms).map((form, index) => ({
    index,
    id: clean(form.id),
    name: clean(form.getAttribute("name")),
    method: clean(form.method || form.getAttribute("method")),
    action: form.action || clean(form.getAttribute("action")),
    fields: Array.from(form.querySelectorAll("input, textarea, select, button")).map(fieldPayload),
  }));
}
"""

EXTRACT_MARKDOWN_SCRIPT = r"""
() => {
  const clean = (value) => value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rects = Array.from(el.getClientRects());
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 &&
      rects.some((rect) => rect.width > 0 && rect.height > 0);
  };
  const inline = (el) => {
    const text = clean(el.innerText || el.textContent);
    if (el.tagName.toLowerCase() === "a" && el.href && text) {
      return "[" + text.replace(/\]/g, "\\]") + "](" + el.href + ")";
    }
    return text;
  };
  const blocks = [];
  for (const el of Array.from(document.body ? document.body.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,blockquote,pre") : [])) {
    if (!visible(el)) {
      continue;
    }
    const tag = el.tagName.toLowerCase();
    let text = clean(el.innerText || el.textContent);
    if (!text) {
      continue;
    }
    if (/^h[1-6]$/.test(tag)) {
      blocks.push("#".repeat(Number(tag.slice(1))) + " " + text);
    } else if (tag === "li") {
      blocks.push("- " + text);
    } else if (tag === "blockquote") {
      blocks.push("> " + text);
    } else if (tag === "pre") {
      blocks.push("```\n" + (el.innerText || el.textContent || "").trim() + "\n```");
    } else {
      const links = Array.from(el.querySelectorAll("a[href]")).filter(visible);
      for (const link of links) {
        const linkText = clean(link.innerText || link.textContent);
        if (linkText) {
          text = text.replace(linkText, inline(link));
        }
      }
      blocks.push(text);
    }
  }
  return blocks.join("\n\n");
}
"""

SCROLL_ELEMENT_SCRIPT = r"""
(el, delta) => {
  el.scrollBy({left: delta.left, top: delta.top, behavior: "instant"});
  return {scrollLeft: el.scrollLeft, scrollTop: el.scrollTop};
}
"""

SCROLL_PAGE_SCRIPT = r"""
(delta) => {
  window.scrollBy({left: delta.left, top: delta.top, behavior: "instant"});
  return {scrollX: window.scrollX, scrollY: window.scrollY};
}
"""


class AgentDaemon:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.context_id: str | None = None
        self.pages: dict[str, Page] = {}
        self.page_serializers: dict[str, DOMSerializer] = {}
        self.downloads: dict[str, dict[str, Any]] = {}
        self._download_objects: dict[str, Any] = {}
        self.dialogs: list[dict[str, Any]] = []
        self.next_dialog_policy: dict[str, dict[str, str]] = {}

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            self.context = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None

    def new_context(self) -> dict[str, Any]:
        context = self._ensure_context()
        self._adopt_pages(context.pages)
        assert self.context_id is not None
        return {
            "context_id": self.context_id,
            "pages": [self._page_payload(page_id, page) for page_id, page in self.pages.items()],
        }

    def new_page(self) -> dict[str, Any]:
        context = self._ensure_context()
        page = context.new_page()
        page_id = self._register_page(page)
        return {"page": self._page_payload(page_id, page)}

    def list_pages(self) -> dict[str, Any]:
        context = self._ensure_context()
        self._adopt_pages(context.pages)
        return {"pages": [self._page_payload(page_id, page) for page_id, page in self.pages.items()]}

    def close_page(self, page_id: str) -> dict[str, Any]:
        page = self._page(page_id)
        with suppress(Exception):
            page.close()
        self.pages.pop(page_id, None)
        self.page_serializers.pop(page_id, None)
        return {"closed": page_id, **self.list_pages()}

    def navigate(
        self,
        page_id: str,
        url: str,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded",
    ) -> dict[str, Any]:
        page = self._page(page_id)
        page.goto(url, wait_until=wait_until, timeout=60_000)
        self._settle(page)
        self.page_serializers.pop(page_id, None)
        return {"page": self._page_payload(page_id, page)}

    def go_back(self, page_id: str) -> dict[str, Any]:
        page = self._page(page_id)
        page.go_back(wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        self.page_serializers.pop(page_id, None)
        return {"page": self._page_payload(page_id, page)}

    def go_forward(self, page_id: str) -> dict[str, Any]:
        page = self._page(page_id)
        page.go_forward(wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        self.page_serializers.pop(page_id, None)
        return {"page": self._page_payload(page_id, page)}

    def reload(self, page_id: str) -> dict[str, Any]:
        page = self._page(page_id)
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)
        self.page_serializers.pop(page_id, None)
        return {"page": self._page_payload(page_id, page)}

    def describe_page(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = DOMSerializer(max_items=max_items)
        snapshot = serializer.serialize(page)
        self.page_serializers[page_id] = serializer
        return {
            "page": self._page_payload(page_id, page),
            "text": snapshot.text,
            "frames": [asdict(frame) for frame in snapshot.frames],
            "items": [asdict(item) for item in snapshot.items],
        }

    def list_page(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
        return self.describe_page(page_id, max_items)

    def click(self, page_id: str, ref: str) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.click(timeout=15_000)
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def element_info(self, page_id: str, ref: str) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = self._serializer_for(page_id, page)
        element = serializer.get_reference(ref).element
        locator = serializer.resolve_locator(page, ref)
        info = locator.evaluate(ELEMENT_INFO_SCRIPT)
        if not isinstance(info, dict):
            raise ValueError(f"Unable to read info for DOM reference: {ref}")
        info["ref"] = ref
        info["frame"] = {
            "index": element.frame_index,
            "url": element.frame_url,
            "name": element.frame_name,
        }
        return {
            "page": self._page_payload(page_id, page),
            "info": info,
            "text": render_element_info(info),
        }

    def fill_text(self, page_id: str, ref: str, text: str, *, submit: bool = False) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.click(timeout=15_000)
        locator.press("ControlOrMeta+A", timeout=15_000)
        locator.press("Backspace", timeout=15_000)
        if text:
            page.keyboard.insert_text(text)
        if submit:
            locator.press("Enter")
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def select_options(
        self,
        page_id: str,
        ref: str,
        values: list[str],
        *,
        by: Literal["value", "label", "index"] = "value",
    ) -> dict[str, Any]:
        if not values:
            raise ValueError("Select requires at least one value.")
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        selected: list[str]
        if by == "index":
            indexes = [int(value) for value in values]
            selected = locator.select_option(
                index=indexes[0] if len(indexes) == 1 else indexes,
                timeout=15_000,
            )
        elif by == "label":
            selected = locator.select_option(
                label=values[0] if len(values) == 1 else values,
                timeout=15_000,
            )
        else:
            selected = locator.select_option(
                value=values[0] if len(values) == 1 else values,
                timeout=15_000,
            )
        self._settle(page)
        result = self.describe_page(page_id)
        result["selected"] = selected
        result["pages"] = self._pages_since(before_pages)
        return result

    def type_text(
        self,
        page_id: str,
        ref: str,
        text: str,
        *,
        submit: bool = False,
    ) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.click(timeout=15_000)
        if text:
            page.keyboard.insert_text(text)
        if submit:
            locator.press("Enter")
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def screenshot(
        self,
        page_id: str,
        path: str,
        *,
        full_page: bool = False,
        ref: str | None = None,
    ) -> dict[str, Any]:
        page = self._page(page_id)
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if ref:
            serializer = self._serializer_for(page_id, page)
            locator = serializer.resolve_locator(page, ref)
            locator.screenshot(path=str(output), timeout=15_000)
        else:
            page.screenshot(path=str(output), full_page=full_page, timeout=30_000)
        return {"page": self._page_payload(page_id, page), "path": str(output)}

    def wait_for(
        self,
        page_id: str,
        *,
        target: str,
        value: str | None = None,
        state: str = "visible",
        timeout_ms: int = 15_000,
    ) -> dict[str, Any]:
        page = self._page(page_id)
        if target in {"load", "domcontentloaded", "networkidle"}:
            load_state = cast(Literal["load", "domcontentloaded", "networkidle"], target)
            page.wait_for_load_state(load_state, timeout=timeout_ms)
        elif target == "timeout":
            page.wait_for_timeout(timeout_ms)
        elif target == "selector":
            if not value:
                raise ValueError("wait --for selector requires a selector value.")
            wait_state = cast(Literal["attached", "detached", "hidden", "visible"], state)
            page.locator(value).first.wait_for(state=wait_state, timeout=timeout_ms)
        elif target == "text":
            if not value:
                raise ValueError("wait --for text requires a text value.")
            wait_state = cast(Literal["attached", "detached", "hidden", "visible"], state)
            page.get_by_text(value).first.wait_for(state=wait_state, timeout=timeout_ms)
        elif target == "url":
            if not value:
                raise ValueError("wait --for url requires a URL pattern.")
            page.wait_for_url(value, timeout=timeout_ms)
        else:
            raise ValueError(f"Unsupported wait target: {target}")
        self._settle(page)
        return {"page": self._page_payload(page_id, page)}

    def press_key(self, page_id: str, key: str, *, ref: str | None = None) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        if ref:
            serializer = self._serializer_for(page_id, page)
            locator = serializer.resolve_locator(page, ref)
            locator.press(key, timeout=15_000)
        else:
            page.keyboard.press(key)
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def hover(self, page_id: str, ref: str) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.hover(timeout=15_000)
        self._settle(page)
        return self.describe_page(page_id)

    def scroll(
        self,
        page_id: str,
        *,
        direction: str,
        amount: int = 600,
        ref: str | None = None,
    ) -> dict[str, Any]:
        page = self._page(page_id)
        delta = _scroll_delta(direction, amount)
        if ref:
            serializer = self._serializer_for(page_id, page)
            locator = serializer.resolve_locator(page, ref)
            locator.evaluate(SCROLL_ELEMENT_SCRIPT, delta)
        else:
            page.evaluate(SCROLL_PAGE_SCRIPT, delta)
        self._settle(page)
        return self.describe_page(page_id)

    def drag(self, page_id: str, source_ref: str, target_ref: str) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        source = serializer.resolve_locator(page, source_ref)
        target = serializer.resolve_locator(page, target_ref)
        if hasattr(source, "drag_to"):
            source.drag_to(target, timeout=15_000)
        else:
            source.hover(timeout=15_000)
            page.mouse.down()
            target.hover(timeout=15_000)
            page.mouse.up()
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def set_checked(self, page_id: str, ref: str, *, checked: bool) -> dict[str, Any]:
        page = self._page(page_id)
        before_pages = set(self.pages)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        if checked:
            locator.check(timeout=15_000)
        else:
            locator.uncheck(timeout=15_000)
        self._settle(page)
        result = self.describe_page(page_id)
        result["pages"] = self._pages_since(before_pages)
        return result

    def upload_files(self, page_id: str, ref: str, paths: list[str]) -> dict[str, Any]:
        if not paths:
            raise ValueError("upload requires at least one file path.")
        page = self._page(page_id)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.set_input_files(paths, timeout=15_000)
        self._settle(page)
        return self.describe_page(page_id)

    def list_downloads(self) -> dict[str, Any]:
        return {"downloads": [self._download_payload(download_id) for download_id in self.downloads]}

    def save_download(self, download_id: str, path: str) -> dict[str, Any]:
        try:
            download = self._download_objects[download_id]
        except KeyError:
            raise KeyError(f"Unknown download: {download_id}") from None
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(output))
        self.downloads[download_id]["saved_as"] = str(output)
        return {"download": self._download_payload(download_id)}

    def dialog(self, page_id: str, action: str, *, text: str = "") -> dict[str, Any]:
        if action == "list":
            return {"dialogs": self.dialogs}
        if action not in {"accept", "dismiss", "fill"}:
            raise ValueError(f"Unsupported dialog action: {action}")
        self.next_dialog_policy[page_id] = {"action": action, "text": text}
        return {"armed": {"page_id": page_id, "action": action, "text": text}}

    def extract(self, page_id: str, format: str) -> dict[str, Any]:
        page = self._page(page_id)
        if format == "html":
            text = page.content()
        elif format == "links":
            text = json.dumps(page.evaluate(EXTRACT_LINKS_SCRIPT), indent=2, ensure_ascii=False)
        elif format == "forms":
            text = json.dumps(page.evaluate(EXTRACT_FORMS_SCRIPT), indent=2, ensure_ascii=False)
        elif format == "markdown":
            text = str(page.evaluate(EXTRACT_MARKDOWN_SCRIPT) or "")
        elif format == "text":
            text = str(page.locator("body").inner_text(timeout=15_000))
        else:
            raise ValueError(f"Unsupported extract format: {format}")
        return {"page": self._page_payload(page_id, page), "format": format, "text": text}

    def _ensure_context(self) -> BrowserContext:
        if self.context:
            return self.context

        user_data_dir = Path(str(self.profile["user_data_dir"]))
        user_data_dir.mkdir(parents=True, exist_ok=True)
        headless = bool(self.profile.get("headless", False))
        humanize = bool(self.profile.get("humanize", True))
        executable_path = resolve_installed_rotunda_executable()

        self.playwright = sync_playwright().start()
        from rotunda.utils import launch_options

        opts = launch_options(
            headless=headless,
            executable_path=executable_path,
            env=dict(os.environ),
            humanize=humanize,
        )
        self.context = self.playwright.firefox.launch_persistent_context(
            str(user_data_dir),
            **opts,
        )

        def on_page(page: Page) -> None:
            self._register_page(page)

        self.context.on(cast(Any, "page"), on_page)

        self.context_id = f"ctx_{uuid.uuid4().hex[:10]}"
        self._adopt_pages(self.context.pages)
        if not self.pages:
            page = self.context.new_page()
            self._register_page(page)
        return self.context

    def _adopt_pages(self, pages: list[Page]) -> list[str]:
        new_page_ids: list[str] = []
        known = set(self.pages.values())
        for page in pages:
            if page not in known:
                new_page_ids.append(self._register_page(page))
                known.add(page)
        return new_page_ids

    def _register_page(self, page: Page) -> str:
        for existing_id, existing_page in self.pages.items():
            if existing_page is page:
                return existing_id
        page_id = f"page_{uuid.uuid4().hex[:10]}"
        self.pages[page_id] = page
        page.on("download", lambda download, page_id=page_id: self._record_download(page_id, download))
        page.on("dialog", lambda dialog, page_id=page_id: self._handle_dialog(page_id, dialog))
        return page_id

    def _page(self, page_id: str) -> Page:
        try:
            return self.pages[page_id]
        except KeyError:
            raise KeyError(f"Unknown page: {page_id}") from None

    def _serializer_for(self, page_id: str, page: Page) -> DOMSerializer:
        serializer = self.page_serializers.get(page_id)
        if serializer is None:
            serializer = DOMSerializer()
            serializer.serialize(page)
            self.page_serializers[page_id] = serializer
        return serializer

    def _settle(self, page: Page) -> None:
        with suppress(Exception):
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        if self.context:
            self._adopt_pages(self.context.pages)

    def _page_payload(self, page_id: str, page: Page) -> dict[str, str]:
        try:
            title = page.title()
        except Exception:
            title = ""
        return {"id": page_id, "url": page.url, "title": title}

    def _pages_since(self, before_pages: set[str]) -> list[dict[str, str]]:
        if self.context:
            self._adopt_pages(self.context.pages)
        return [
            self._page_payload(page_id, page)
            for page_id, page in self.pages.items()
            if page_id not in before_pages
        ]

    def _record_download(self, page_id: str, download: Any) -> None:
        download_id = f"down_{uuid.uuid4().hex[:10]}"
        self._download_objects[download_id] = download
        self.downloads[download_id] = {
            "id": download_id,
            "page_id": page_id,
            "url": getattr(download, "url", ""),
            "suggested_filename": getattr(download, "suggested_filename", ""),
            "created_at": time.time(),
        }

    def _download_payload(self, download_id: str) -> dict[str, Any]:
        try:
            download = self._download_objects[download_id]
            path = download.path()
        except Exception:
            path = ""
        payload = dict(self.downloads[download_id])
        payload["path"] = str(path or "")
        return payload

    def _handle_dialog(self, page_id: str, dialog: Any) -> None:
        policy = self.next_dialog_policy.pop(page_id, {"action": "dismiss", "text": ""})
        action = policy.get("action") or "dismiss"
        prompt_text = policy.get("text") or ""
        record = {
            "id": f"dialog_{uuid.uuid4().hex[:10]}",
            "page_id": page_id,
            "type": getattr(dialog, "type", ""),
            "message": getattr(dialog, "message", ""),
            "default_value": getattr(dialog, "default_value", ""),
            "action": action,
            "created_at": time.time(),
        }
        try:
            if action == "dismiss":
                dialog.dismiss()
            elif action == "fill":
                dialog.accept(prompt_text=prompt_text)
            else:
                dialog.accept()
        except Exception as exc:
            record["error"] = str(exc)
        self.dialogs.append(record)


class AgentHTTPServer(HTTPServer):
    daemon: AgentDaemon
    token: str


class AgentRequestHandler(BaseHTTPRequestHandler):
    server: AgentHTTPServer

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path == "/ping":
            self._json({"ok": True, "profile_id": self.server.daemon.profile["id"]})
            return
        self._json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            payload = self._read_payload()
            if self.path == "/new-context":
                result = self.server.daemon.new_context()
            elif self.path == "/new-page":
                result = self.server.daemon.new_page()
            elif self.path == "/pages":
                result = self.server.daemon.list_pages()
            elif self.path == "/close-page":
                result = self.server.daemon.close_page(str(payload["page_id"]))
            elif self.path == "/navigate":
                wait_until = _wait_until(str(payload.get("wait_until") or "domcontentloaded"))
                result = self.server.daemon.navigate(
                    str(payload["page_id"]),
                    str(payload["url"]),
                    wait_until,
                )
            elif self.path == "/back":
                result = self.server.daemon.go_back(str(payload["page_id"]))
            elif self.path == "/forward":
                result = self.server.daemon.go_forward(str(payload["page_id"]))
            elif self.path == "/reload":
                result = self.server.daemon.reload(str(payload["page_id"]))
            elif self.path in {"/describe", "/list"}:
                result = self.server.daemon.describe_page(
                    str(payload["page_id"]),
                    int(payload.get("max_items") or 200),
                )
            elif self.path == "/click":
                result = self.server.daemon.click(str(payload["page_id"]), str(payload["ref"]))
            elif self.path == "/info":
                result = self.server.daemon.element_info(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                )
            elif self.path == "/fill":
                result = self.server.daemon.fill_text(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    str(payload["text"]),
                    submit=bool(payload.get("submit", False)),
                )
            elif self.path == "/select":
                result = self.server.daemon.select_options(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    _string_list(payload.get("values")),
                    by=_select_by(str(payload.get("by") or "value")),
                )
            elif self.path == "/type":
                result = self.server.daemon.type_text(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    str(payload["text"]),
                    submit=bool(payload.get("submit", False)),
                )
            elif self.path == "/screenshot":
                result = self.server.daemon.screenshot(
                    str(payload["page_id"]),
                    str(payload["path"]),
                    full_page=bool(payload.get("full_page", False)),
                    ref=str(payload["ref"]) if payload.get("ref") else None,
                )
            elif self.path == "/wait":
                result = self.server.daemon.wait_for(
                    str(payload["page_id"]),
                    target=str(payload["target"]),
                    value=str(payload["value"]) if payload.get("value") is not None else None,
                    state=str(payload.get("state") or "visible"),
                    timeout_ms=int(payload.get("timeout_ms") or 15_000),
                )
            elif self.path == "/press":
                result = self.server.daemon.press_key(
                    str(payload["page_id"]),
                    str(payload["key"]),
                    ref=str(payload["ref"]) if payload.get("ref") else None,
                )
            elif self.path == "/hover":
                result = self.server.daemon.hover(str(payload["page_id"]), str(payload["ref"]))
            elif self.path == "/scroll":
                result = self.server.daemon.scroll(
                    str(payload["page_id"]),
                    direction=str(payload["direction"]),
                    amount=int(payload.get("amount") or 600),
                    ref=str(payload["ref"]) if payload.get("ref") else None,
                )
            elif self.path == "/drag":
                result = self.server.daemon.drag(
                    str(payload["page_id"]),
                    str(payload["source_ref"]),
                    str(payload["target_ref"]),
                )
            elif self.path == "/check":
                result = self.server.daemon.set_checked(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    checked=True,
                )
            elif self.path == "/uncheck":
                result = self.server.daemon.set_checked(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    checked=False,
                )
            elif self.path == "/upload":
                result = self.server.daemon.upload_files(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    _string_list(payload.get("paths")),
                )
            elif self.path == "/downloads":
                result = self.server.daemon.list_downloads()
            elif self.path == "/save-download":
                result = self.server.daemon.save_download(
                    str(payload["download_id"]),
                    str(payload["path"]),
                )
            elif self.path == "/dialog":
                result = self.server.daemon.dialog(
                    str(payload["page_id"]),
                    str(payload["action"]),
                    text=str(payload.get("text") or ""),
                )
            elif self.path == "/extract":
                result = self.server.daemon.extract(str(payload["page_id"]), str(payload["format"]))
            elif self.path == "/shutdown":
                result = {"stopping": True}
                self._json({"ok": True, **result})
                self.server.daemon.close()
                signal.raise_signal(signal.SIGTERM)
                return
            else:
                self._json({"ok": False, "error": "Not found"}, status=404)
                return
            self._json({"ok": True, **result})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, status=500)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        if self.headers.get("Authorization") != expected:
            self._json({"ok": False, "error": "Unauthorized"}, status=401)
            return False
        return True

    def _read_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def render_element_info(info: dict[str, Any]) -> str:
    lines = [f"[{info.get('ref', '')}] {info.get('tag', 'element')}"]
    frame = info.get("frame")
    if isinstance(frame, dict):
        frame_label = f"frame={frame.get('index')}"
        if frame.get("name"):
            frame_label += f" name={frame['name']!r}"
        if frame.get("url"):
            frame_label += f" url={frame['url']}"
        lines.append(frame_label)

    for key in ("role", "name", "value", "text"):
        value = info.get(key)
        if value not in (None, ""):
            lines.append(f"{key}: {value}")

    attributes = info.get("attributes")
    if isinstance(attributes, dict) and attributes:
        lines.append("attributes:")
        for key in sorted(attributes):
            lines.append(f"  {key}: {attributes[key]}")

    state = info.get("state")
    if isinstance(state, dict) and state:
        state_values = ", ".join(f"{key}={value}" for key, value in sorted(state.items()))
        lines.append(f"state: {state_values}")

    bounds = info.get("bounds")
    if isinstance(bounds, dict):
        lines.append(
            "bounds: "
            f"x={bounds.get('x')} y={bounds.get('y')} "
            f"width={bounds.get('width')} height={bounds.get('height')}"
        )

    if "selectedIndex" in info:
        lines.append(f"selectedIndex: {info.get('selectedIndex')}")
    selected_values = info.get("selectedValues")
    if isinstance(selected_values, list):
        lines.append(f"selectedValues: {json.dumps(selected_values)}")

    options = info.get("options")
    if isinstance(options, list):
        lines.append("options:")
        for option in options:
            if not isinstance(option, dict):
                continue
            flags = []
            if option.get("selected"):
                flags.append("selected")
            if option.get("disabled"):
                flags.append("disabled")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(
                f"  [{option.get('index')}] "
                f"value={option.get('value')!r} "
                f"label={option.get('label')!r} "
                f"text={option.get('text')!r}{suffix}"
            )

    outer_html = str(info.get("outerHTML") or "")
    if outer_html:
        if len(outer_html) > 2000:
            outer_html = outer_html[:1997].rstrip() + "..."
        lines.append("outerHTML:")
        lines.append(outer_html)

    return "\n".join(lines)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError("Expected a string or list of strings.")


def _select_by(value: str) -> Literal["value", "label", "index"]:
    if value in {"value", "label", "index"}:
        return cast(Literal["value", "label", "index"], value)
    raise ValueError(f"Unsupported select mode: {value}")


def _scroll_delta(direction: str, amount: int) -> dict[str, int]:
    if direction == "down":
        return {"left": 0, "top": amount}
    if direction == "up":
        return {"left": 0, "top": -amount}
    if direction == "right":
        return {"left": amount, "top": 0}
    if direction == "left":
        return {"left": -amount, "top": 0}
    raise ValueError(f"Unsupported scroll direction: {direction}")


def resolve_installed_rotunda_executable() -> str:
    from rotunda.exceptions import RotundaNotInstalled
    from rotunda.pkgman import launch_path, rotunda_path

    try:
        return launch_path(rotunda_path(download_if_missing=False))
    except RotundaNotInstalled as exc:
        message = str(exc)
        if "rotunda fetch" not in message:
            message = f"{message} Run `rotunda fetch` to install the latest build."
        raise RotundaNotInstalled(message) from exc


@click.command()
@click.option("--profile-id", required=True)
@click.option("--token", required=True)
@click.option("--ready-file", required=True, type=click.Path(path_type=Path))
@click.option("--session-file", required=True, type=click.Path(path_type=Path))
def main(profile_id: str, token: str, ready_file: Path, session_file: Path) -> None:
    run_daemon(
        profile_id=profile_id,
        token=token,
        ready_file=ready_file,
        session_file=session_file,
    )


def run_daemon(
    *,
    profile_id: str,
    token: str,
    ready_file: Path,
    session_file: Path,
) -> None:
    hide_macos_dock_icon()
    store = AgentStore()
    try:
        profile = store.load_profile(profile_id)
        daemon = AgentDaemon(profile)
        server = AgentHTTPServer(("127.0.0.1", 0), AgentRequestHandler)
        server.daemon = daemon
        server.token = token
        host = str(server.server_address[0])
        port = int(server.server_address[1])
        session = {
            "profile_id": profile_id,
            "host": host,
            "port": port,
            "token": token,
            "pid": os.getpid(),
            "started_at": time.time(),
        }
        session_file.write_text(json.dumps(session, indent=2), encoding="utf-8")
        ready_file.write_text(
            json.dumps({"ok": True, "session": session}),
            encoding="utf-8",
        )
        server.serve_forever()
    except Exception as exc:
        ready_file.write_text(
            json.dumps({"ok": False, "error": str(exc)}),
            encoding="utf-8",
        )
        raise


def hide_macos_dock_icon() -> None:
    if sys.platform != "darwin":
        return

    with suppress(Exception):
        import ctypes
        from ctypes import Structure, byref, c_int32, c_uint32

        class ProcessSerialNumber(Structure):
            _fields_ = [
                ("highLongOfPSN", c_uint32),
                ("lowLongOfPSN", c_uint32),
            ]

        current_process = ProcessSerialNumber(0, 2)
        transform_to_background_application = 2
        app_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        app_services.TransformProcessType.argtypes = [
            ctypes.POINTER(ProcessSerialNumber),
            c_uint32,
        ]
        app_services.TransformProcessType.restype = c_int32
        app_services.TransformProcessType(
            byref(current_process),
            transform_to_background_application,
        )


def _wait_until(value: str) -> Literal["commit", "domcontentloaded", "load", "networkidle"]:
    if value in {"commit", "domcontentloaded", "load", "networkidle"}:
        return cast(Literal["commit", "domcontentloaded", "load", "networkidle"], value)
    raise ValueError(f"Unsupported wait_until value: {value}")


if __name__ == "__main__":
    main()
