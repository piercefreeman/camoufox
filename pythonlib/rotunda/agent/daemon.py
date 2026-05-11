from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Literal, cast

import rich_click as click
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from .dom import DomDiff, render_action_change
from .dom_serializer import DOMSerializer, DOMSnapshot
from .runtime import (
    AGENT_HOST,
    AGENT_IDENTITY_SERVICE,
    AGENT_PORT_BASE,
    AGENT_PORT_COUNT,
    HEARTBEAT_INTERVAL_SECONDS,
    agent_ports,
)
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


def _page_url(page: Page) -> str:
    return str(getattr(page, "url", "") or "")


class AgentDaemon:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.context_id: str | None = None
        self.pages: dict[str, Page] = {}
        self.page_serializers: dict[str, DOMSerializer] = {}
        self.page_snapshots: dict[str, DOMSnapshot] = {}
        self.downloads: dict[str, dict[str, Any]] = {}
        self._download_objects: dict[str, Any] = {}
        self.dialogs: list[dict[str, Any]] = []
        self.next_dialog_policy: dict[str, dict[str, str]] = {}
        self._context_lock = asyncio.Lock()
        self._page_locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = None
            self.pages.clear()
            self.page_serializers.clear()
            self.page_snapshots.clear()
            self._page_locks.clear()
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

    async def new_context(self) -> dict[str, Any]:
        context = await self._ensure_context()
        self._adopt_pages(context.pages)
        assert self.context_id is not None
        return {
            "context_id": self.context_id,
            "pages": await self._page_payloads(self.pages.items()),
        }

    async def new_page(self) -> dict[str, Any]:
        context = await self._ensure_context()
        async with self._context_lock:
            page = await context.new_page()
            page_id = self._register_page(page)
        return {"page": await self._page_payload(page_id, page)}

    async def list_pages(self) -> dict[str, Any]:
        context = await self._ensure_context()
        self._adopt_pages(context.pages)
        return {"pages": await self._page_payloads(self.pages.items())}

    async def close_page(self, page_id: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            with suppress(Exception):
                await page.close()
            self.pages.pop(page_id, None)
            self.page_serializers.pop(page_id, None)
            self.page_snapshots.pop(page_id, None)
            self._page_locks.pop(page_id, None)
        return {"closed": page_id, **await self.list_pages()}

    async def navigate(
        self,
        page_id: str,
        url: str,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded",
    ) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            await page.goto(url, wait_until=wait_until, timeout=60_000)
            await self._settle(page)
            self.page_serializers.pop(page_id, None)
            self.page_snapshots.pop(page_id, None)
            return {"page": await self._page_payload(page_id, page)}

    async def go_back(self, page_id: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            await page.go_back(wait_until="domcontentloaded", timeout=60_000)
            await self._settle(page)
            self.page_serializers.pop(page_id, None)
            self.page_snapshots.pop(page_id, None)
            return {"page": await self._page_payload(page_id, page)}

    async def go_forward(self, page_id: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            await page.go_forward(wait_until="domcontentloaded", timeout=60_000)
            await self._settle(page)
            self.page_serializers.pop(page_id, None)
            self.page_snapshots.pop(page_id, None)
            return {"page": await self._page_payload(page_id, page)}

    async def reload(self, page_id: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            await self._settle(page)
            self.page_serializers.pop(page_id, None)
            self.page_snapshots.pop(page_id, None)
            return {"page": await self._page_payload(page_id, page)}

    async def describe_page(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
        async with self._page_lock(page_id):
            return await self._describe_page_unlocked(page_id, max_items)

    async def list_page(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
        return await self.describe_page(page_id, max_items)

    async def click(self, page_id: str, ref: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            await locator.click(timeout=15_000)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def element_info(self, page_id: str, ref: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            serializer = await self._serializer_for(page_id, page)
            element = serializer.get_reference(ref).element
            locator = await serializer.async_resolve_locator(page, ref)
            info = await locator.evaluate(ELEMENT_INFO_SCRIPT)
            if not isinstance(info, dict):
                raise ValueError(f"Unable to read info for DOM reference: {ref}")
            info["ref"] = ref
            info["frame"] = {
                "index": element.frame_index,
                "url": element.frame_url,
                "name": element.frame_name,
            }
            return {
                "page": await self._page_payload(page_id, page),
                "info": info,
                "text": render_element_info(info),
            }

    async def fill_text(self, page_id: str, ref: str, text: str, *, submit: bool = False) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            await locator.click(timeout=15_000)
            await locator.press("ControlOrMeta+A", timeout=15_000)
            await locator.press("Backspace", timeout=15_000)
            if text:
                await page.keyboard.insert_text(text)
            if submit:
                await locator.press("Enter")
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def select_options(
        self,
        page_id: str,
        ref: str,
        values: list[str],
        *,
        by: Literal["value", "label", "index"] = "value",
    ) -> dict[str, Any]:
        if not values:
            raise ValueError("Select requires at least one value.")
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            selected: list[str]
            if by == "index":
                indexes = [int(value) for value in values]
                selected = await locator.select_option(
                    index=indexes[0] if len(indexes) == 1 else indexes,
                    timeout=15_000,
                )
            elif by == "label":
                selected = await locator.select_option(
                    label=values[0] if len(values) == 1 else values,
                    timeout=15_000,
                )
            else:
                selected = await locator.select_option(
                    value=values[0] if len(values) == 1 else values,
                    timeout=15_000,
                )
            await self._settle(page)
            result = await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)
            result["selected"] = selected
            return result

    async def type_text(
        self,
        page_id: str,
        ref: str,
        text: str,
        *,
        submit: bool = False,
    ) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            await locator.click(timeout=15_000)
            if text:
                await page.keyboard.insert_text(text)
            if submit:
                await locator.press("Enter")
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def screenshot(
        self,
        page_id: str,
        path: str,
        *,
        full_page: bool = False,
        ref: str | None = None,
    ) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            if ref:
                serializer = await self._serializer_for(page_id, page)
                locator = await serializer.async_resolve_locator(page, ref)
                await locator.screenshot(path=str(output), timeout=15_000)
            else:
                await page.screenshot(path=str(output), full_page=full_page, timeout=30_000)
            return {"page": await self._page_payload(page_id, page), "path": str(output)}

    async def wait_for(
        self,
        page_id: str,
        *,
        target: str,
        value: str | None = None,
        state: str = "visible",
        timeout_ms: int = 15_000,
    ) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            if target in {"load", "domcontentloaded", "networkidle"}:
                load_state = cast(Literal["load", "domcontentloaded", "networkidle"], target)
                await page.wait_for_load_state(load_state, timeout=timeout_ms)
            elif target == "timeout":
                await page.wait_for_timeout(timeout_ms)
            elif target == "selector":
                if not value:
                    raise ValueError("wait --for selector requires a selector value.")
                wait_state = cast(Literal["attached", "detached", "hidden", "visible"], state)
                await page.locator(value).first.wait_for(state=wait_state, timeout=timeout_ms)
            elif target == "text":
                if not value:
                    raise ValueError("wait --for text requires a text value.")
                wait_state = cast(Literal["attached", "detached", "hidden", "visible"], state)
                await page.get_by_text(value).first.wait_for(state=wait_state, timeout=timeout_ms)
            elif target == "url":
                if not value:
                    raise ValueError("wait --for url requires a URL pattern.")
                await page.wait_for_url(value, timeout=timeout_ms)
            else:
                raise ValueError(f"Unsupported wait target: {target}")
            await self._settle(page)
            return {"page": await self._page_payload(page_id, page)}

    async def press_key(self, page_id: str, key: str, *, ref: str | None = None) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
                need_serializer=ref is not None,
            )
            if ref:
                assert serializer is not None
                locator = await serializer.async_resolve_locator(page, ref)
                await locator.press(key, timeout=15_000)
            else:
                await page.keyboard.press(key)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def hover(self, page_id: str, ref: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            await locator.hover(timeout=15_000)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def scroll(
        self,
        page_id: str,
        *,
        direction: str,
        amount: int = 600,
        ref: str | None = None,
    ) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
                need_serializer=ref is not None,
            )
            delta = _scroll_delta(direction, amount)
            if ref:
                assert serializer is not None
                locator = await serializer.async_resolve_locator(page, ref)
                await locator.evaluate(SCROLL_ELEMENT_SCRIPT, delta)
            else:
                await page.evaluate(SCROLL_PAGE_SCRIPT, delta)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def drag(self, page_id: str, source_ref: str, target_ref: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            source = await serializer.async_resolve_locator(page, source_ref)
            target = await serializer.async_resolve_locator(page, target_ref)
            if hasattr(source, "drag_to"):
                await source.drag_to(target, timeout=15_000)
            else:
                await source.hover(timeout=15_000)
                await page.mouse.down()
                await target.hover(timeout=15_000)
                await page.mouse.up()
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def set_checked(self, page_id: str, ref: str, *, checked: bool) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            if checked:
                await locator.check(timeout=15_000)
            else:
                await locator.uncheck(timeout=15_000)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def upload_files(self, page_id: str, ref: str, paths: list[str]) -> dict[str, Any]:
        if not paths:
            raise ValueError("upload requires at least one file path.")
        async with self._page_lock(page_id):
            page = self._page(page_id)
            before_pages, before_url, before_snapshot, serializer = await self._action_baseline_unlocked(
                page_id,
                page,
            )
            assert serializer is not None
            locator = await serializer.async_resolve_locator(page, ref)
            await locator.set_input_files(paths, timeout=15_000)
            await self._settle(page)
            return await self._action_result_unlocked(page_id, page, before_pages, before_url, before_snapshot)

    async def list_downloads(self) -> dict[str, Any]:
        downloads = [await self._download_payload(download_id) for download_id in self.downloads]
        return {"downloads": downloads}

    async def save_download(self, download_id: str, path: str) -> dict[str, Any]:
        try:
            download = self._download_objects[download_id]
        except KeyError:
            raise KeyError(f"Unknown download: {download_id}") from None
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(str(output))
        self.downloads[download_id]["saved_as"] = str(output)
        return {"download": await self._download_payload(download_id)}

    async def dialog(self, page_id: str, action: str, *, text: str = "") -> dict[str, Any]:
        if action == "list":
            return {"dialogs": self.dialogs}
        if action not in {"accept", "dismiss", "fill"}:
            raise ValueError(f"Unsupported dialog action: {action}")
        self.next_dialog_policy[page_id] = {"action": action, "text": text}
        return {"armed": {"page_id": page_id, "action": action, "text": text}}

    async def extract(self, page_id: str, format: str) -> dict[str, Any]:
        async with self._page_lock(page_id):
            page = self._page(page_id)
            if format == "html":
                text = await page.content()
            elif format == "links":
                text = json.dumps(await page.evaluate(EXTRACT_LINKS_SCRIPT), indent=2, ensure_ascii=False)
            elif format == "forms":
                text = json.dumps(await page.evaluate(EXTRACT_FORMS_SCRIPT), indent=2, ensure_ascii=False)
            elif format == "markdown":
                text = str(await page.evaluate(EXTRACT_MARKDOWN_SCRIPT) or "")
            elif format == "text":
                text = str(await page.locator("body").inner_text(timeout=15_000))
            else:
                raise ValueError(f"Unsupported extract format: {format}")
            return {"page": await self._page_payload(page_id, page), "format": format, "text": text}

    async def _ensure_context(self) -> BrowserContext:
        if self.context:
            return self.context

        async with self._context_lock:
            if self.context:
                return self.context

            user_data_dir = Path(str(self.profile["user_data_dir"]))
            user_data_dir.mkdir(parents=True, exist_ok=True)
            headless = bool(self.profile.get("headless", False))
            humanize = bool(self.profile.get("humanize", True))
            executable_path = resolve_installed_rotunda_executable()

            self.playwright = await async_playwright().start()
            from rotunda.utils import (
                launch_options,
                persistent_context_options,
                runtime_profile_init_script,
            )

            env: dict[str, str | int | float] = dict(os.environ)
            opts = await asyncio.to_thread(
                launch_options,
                headless=headless,
                executable_path=executable_path,
                env=env,
                humanize=humanize,
            )
            context_opts = persistent_context_options(opts)
            self.context = await self.playwright.firefox.launch_persistent_context(
                str(user_data_dir),
                **context_opts,
            )
            profile_path = opts.get("env", {}).get("ROTUNDA_CONFIG_PATH")
            if profile_path:
                runtime_profile = json.loads(Path(str(profile_path)).read_text(encoding="utf-8"))
                init_script = runtime_profile_init_script(runtime_profile)
                if init_script:
                    await self.context.add_init_script(init_script)

            def on_page(page: Page) -> None:
                self._register_page(page)

            self.context.on(cast(Any, "page"), on_page)

            self.context_id = f"ctx_{uuid.uuid4().hex[:10]}"
            self._adopt_pages(self.context.pages)
            if not self.pages:
                page = await self.context.new_page()
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
        self._page_locks[page_id] = asyncio.Lock()
        page.on("download", lambda download, page_id=page_id: self._record_download(page_id, download))
        page.on(
            "dialog",
            lambda dialog, page_id=page_id: asyncio.create_task(self._handle_dialog(page_id, dialog)),
        )
        return page_id

    def _page(self, page_id: str) -> Page:
        try:
            return self.pages[page_id]
        except KeyError:
            raise KeyError(f"Unknown page: {page_id}") from None

    def _page_lock(self, page_id: str) -> asyncio.Lock:
        lock = self._page_locks.get(page_id)
        if lock is None:
            lock = asyncio.Lock()
            self._page_locks[page_id] = lock
        return lock

    async def _action_baseline_unlocked(
        self,
        page_id: str,
        page: Page,
        *,
        need_serializer: bool = True,
    ) -> tuple[set[str], str, DOMSnapshot | None, DOMSerializer | None]:
        before_pages = set(self.pages)
        serializer = self.page_serializers.get(page_id)
        if need_serializer or self.page_snapshots.get(page_id) is None:
            serializer = await self._serializer_for(page_id, page)
        return before_pages, _page_url(page), self.page_snapshots.get(page_id), serializer

    async def _serializer_for(self, page_id: str, page: Page) -> DOMSerializer:
        serializer = self.page_serializers.get(page_id)
        if serializer is None:
            serializer = DOMSerializer()
            self.page_serializers[page_id] = serializer
        if page_id not in self.page_snapshots and hasattr(serializer, "async_serialize"):
            self.page_snapshots[page_id] = await serializer.async_serialize(page)
        return serializer

    async def _describe_page_unlocked(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = self.page_serializers.get(page_id)
        if serializer is None:
            serializer = DOMSerializer(max_items=max_items)
            self.page_serializers[page_id] = serializer
        else:
            serializer.max_items = max_items
        snapshot = await serializer.async_serialize(page)
        self.page_snapshots[page_id] = snapshot
        return {
            "page": await self._page_payload(page_id, page),
            "text": snapshot.text,
            "frames": [asdict(frame) for frame in snapshot.frames],
            "items": [asdict(item) for item in snapshot.items],
        }

    async def _action_result_unlocked(
        self,
        page_id: str,
        page: Page,
        before_pages: set[str],
        before_url: str,
        before_snapshot: DOMSnapshot | None,
    ) -> dict[str, Any]:
        result = await self._describe_page_unlocked(page_id)
        new_pages = await self._pages_since(before_pages)
        after_snapshot = self.page_snapshots.get(page_id)
        change = DomDiff.from_snapshots(
            before_snapshot,
            after_snapshot,
            before_url=before_url,
            after_url=str(result.get("page", {}).get("url") or _page_url(page)),
            new_page_count=len(new_pages),
        ).action_change()
        result["pages"] = new_pages
        result["change"] = change.to_payload()
        result["text"] = render_action_change(change)
        return result

    async def _settle(self, page: Page) -> None:
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        if self.context:
            self._adopt_pages(self.context.pages)

    async def _page_payload(self, page_id: str, page: Page) -> dict[str, str]:
        try:
            title = await page.title()
        except Exception:
            title = ""
        return {"id": page_id, "url": page.url, "title": title}

    async def _page_payloads(self, pages: Any) -> list[dict[str, str]]:
        return [await self._page_payload(page_id, page) for page_id, page in list(pages)]

    async def _pages_since(self, before_pages: set[str]) -> list[dict[str, str]]:
        if self.context:
            self._adopt_pages(self.context.pages)
        return [
            await self._page_payload(page_id, page)
            for page_id, page in list(self.pages.items())
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

    async def _download_payload(self, download_id: str) -> dict[str, Any]:
        try:
            download = self._download_objects[download_id]
            path = await download.path()
        except Exception:
            path = ""
        payload = dict(self.downloads[download_id])
        payload["path"] = str(path or "")
        return payload

    async def _handle_dialog(self, page_id: str, dialog: Any) -> None:
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
                await dialog.dismiss()
            elif action == "fill":
                await dialog.accept(prompt_text=prompt_text)
            else:
                await dialog.accept()
        except Exception as exc:
            record["error"] = str(exc)
        self.dialogs.append(record)


class AgentRouteNotFound(Exception):
    pass


class AgentHTTPServer(ThreadingMixIn, HTTPServer):
    daemon: AgentDaemon
    token: str
    loop: asyncio.AbstractEventLoop
    instance_id: str
    started_at: float
    update_tick: float
    daemon_threads = True

    def run_agent(self, awaitable: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(awaitable, self.loop)
        return future.result()

    def initiate_shutdown(self) -> None:
        def shutdown() -> None:
            with suppress(Exception):
                self.run_agent(self.daemon.close())
            self.shutdown()

        threading.Thread(target=shutdown, name="rotunda-agent-shutdown", daemon=True).start()


class AgentRequestHandler(BaseHTTPRequestHandler):
    server: AgentHTTPServer

    def do_GET(self) -> None:
        if self.path == "/identity":
            self._json(
                {
                    "ok": True,
                    "service": AGENT_IDENTITY_SERVICE,
                    "profile_id": self.server.daemon.profile["id"],
                    "host": AGENT_HOST,
                    "port": int(self.server.server_address[1]),
                    "pid": os.getpid(),
                    "started_at": self.server.started_at,
                    "instance_id": self.server.instance_id,
                    "update_tick": self.server.update_tick,
                }
            )
            return
        if not self._authorized():
            return
        if self.path == "/ping":
            self._json(
                {
                    "ok": True,
                    "profile_id": self.server.daemon.profile["id"],
                    "instance_id": self.server.instance_id,
                    "update_tick": self.server.update_tick,
                }
            )
            return
        self._json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            payload = self._read_payload()
            if self.path == "/shutdown":
                self._json({"ok": True, "stopping": True})
                self.server.initiate_shutdown()
                return
            result = self.server.run_agent(_dispatch_agent_request(self.server.daemon, self.path, payload))
            self._json({"ok": True, **result})
        except AgentRouteNotFound:
            self._json({"ok": False, "error": "Not found"}, status=404)
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


async def _dispatch_agent_request(
    daemon: AgentDaemon,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if path == "/new-context":
        return await daemon.new_context()
    if path == "/new-page":
        return await daemon.new_page()
    if path == "/pages":
        return await daemon.list_pages()
    if path == "/close-page":
        return await daemon.close_page(str(payload["page_id"]))
    if path == "/navigate":
        wait_until = _wait_until(str(payload.get("wait_until") or "domcontentloaded"))
        return await daemon.navigate(
            str(payload["page_id"]),
            str(payload["url"]),
            wait_until,
        )
    if path == "/back":
        return await daemon.go_back(str(payload["page_id"]))
    if path == "/forward":
        return await daemon.go_forward(str(payload["page_id"]))
    if path == "/reload":
        return await daemon.reload(str(payload["page_id"]))
    if path in {"/describe", "/list"}:
        return await daemon.describe_page(
            str(payload["page_id"]),
            int(payload.get("max_items") or 200),
        )
    if path == "/click":
        return await daemon.click(str(payload["page_id"]), str(payload["ref"]))
    if path == "/info":
        return await daemon.element_info(
            str(payload["page_id"]),
            str(payload["ref"]),
        )
    if path == "/fill":
        return await daemon.fill_text(
            str(payload["page_id"]),
            str(payload["ref"]),
            str(payload["text"]),
            submit=bool(payload.get("submit", False)),
        )
    if path == "/select":
        return await daemon.select_options(
            str(payload["page_id"]),
            str(payload["ref"]),
            _string_list(payload.get("values")),
            by=_select_by(str(payload.get("by") or "value")),
        )
    if path == "/type":
        return await daemon.type_text(
            str(payload["page_id"]),
            str(payload["ref"]),
            str(payload["text"]),
            submit=bool(payload.get("submit", False)),
        )
    if path == "/screenshot":
        return await daemon.screenshot(
            str(payload["page_id"]),
            str(payload["path"]),
            full_page=bool(payload.get("full_page", False)),
            ref=str(payload["ref"]) if payload.get("ref") else None,
        )
    if path == "/wait":
        return await daemon.wait_for(
            str(payload["page_id"]),
            target=str(payload["target"]),
            value=str(payload["value"]) if payload.get("value") is not None else None,
            state=str(payload.get("state") or "visible"),
            timeout_ms=int(payload.get("timeout_ms") or 15_000),
        )
    if path == "/press":
        return await daemon.press_key(
            str(payload["page_id"]),
            str(payload["key"]),
            ref=str(payload["ref"]) if payload.get("ref") else None,
        )
    if path == "/hover":
        return await daemon.hover(str(payload["page_id"]), str(payload["ref"]))
    if path == "/scroll":
        return await daemon.scroll(
            str(payload["page_id"]),
            direction=str(payload["direction"]),
            amount=int(payload.get("amount") or 600),
            ref=str(payload["ref"]) if payload.get("ref") else None,
        )
    if path == "/drag":
        return await daemon.drag(
            str(payload["page_id"]),
            str(payload["source_ref"]),
            str(payload["target_ref"]),
        )
    if path == "/check":
        return await daemon.set_checked(
            str(payload["page_id"]),
            str(payload["ref"]),
            checked=True,
        )
    if path == "/uncheck":
        return await daemon.set_checked(
            str(payload["page_id"]),
            str(payload["ref"]),
            checked=False,
        )
    if path == "/upload":
        return await daemon.upload_files(
            str(payload["page_id"]),
            str(payload["ref"]),
            _string_list(payload.get("paths")),
        )
    if path == "/downloads":
        return await daemon.list_downloads()
    if path == "/save-download":
        return await daemon.save_download(
            str(payload["download_id"]),
            str(payload["path"]),
        )
    if path == "/dialog":
        return await daemon.dialog(
            str(payload["page_id"]),
            str(payload["action"]),
            text=str(payload.get("text") or ""),
        )
    if path == "/extract":
        return await daemon.extract(str(payload["page_id"]), str(payload["format"]))
    raise AgentRouteNotFound


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
@click.option("--token", default=None)
@click.option("--token-file", default=None, type=click.Path(path_type=Path))
@click.option("--ready-file", required=True, type=click.Path(path_type=Path))
@click.option("--session-file", required=True, type=click.Path(path_type=Path))
@click.option("--port-base", default=AGENT_PORT_BASE, show_default=True, type=int)
@click.option("--port-count", default=AGENT_PORT_COUNT, show_default=True, type=int)
def main(
    profile_id: str,
    token: str | None,
    token_file: Path | None,
    ready_file: Path,
    session_file: Path,
    port_base: int,
    port_count: int,
) -> None:
    resolved_token = token or _load_auth_token(token_file)
    if not resolved_token:
        raise click.ClickException("Agent daemon requires --token or --token-file.")
    run_daemon(
        profile_id=profile_id,
        token=resolved_token,
        ready_file=ready_file,
        session_file=session_file,
        port_base=port_base,
        port_count=port_count,
    )


def run_daemon(
    *,
    profile_id: str,
    token: str,
    ready_file: Path,
    session_file: Path,
    port_base: int = AGENT_PORT_BASE,
    port_count: int = AGENT_PORT_COUNT,
) -> None:
    hide_macos_dock_icon()
    store = AgentStore()
    loop: asyncio.AbstractEventLoop | None = None
    loop_thread: threading.Thread | None = None
    server: AgentHTTPServer | None = None
    heartbeat_stop: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None
    instance_id = f"daemon_{uuid.uuid4().hex[:12]}"
    try:
        profile = store.load_profile(profile_id)
        daemon = AgentDaemon(profile)
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(
            target=_run_agent_loop,
            args=(loop,),
            name=f"rotunda-agent-{profile_id}",
            daemon=True,
        )
        loop_thread.start()
        server = _bind_agent_server(port_base=port_base, port_count=port_count)
        server.daemon = daemon
        server.token = token
        server.loop = loop
        server.instance_id = instance_id
        server.started_at = time.time()
        server.update_tick = server.started_at
        host = str(server.server_address[0])
        port = int(server.server_address[1])
        session = {
            "profile_id": profile_id,
            "host": host,
            "port": port,
            "token": token,
            "pid": os.getpid(),
            "started_at": server.started_at,
            "instance_id": instance_id,
            "update_tick": server.update_tick,
        }
        _write_daemon_state(store, profile_id, session_file, session)
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_heartbeat_daemon_state,
            args=(store, profile_id, session_file, session, server, heartbeat_stop),
            name=f"rotunda-agent-heartbeat-{profile_id}",
            daemon=True,
        )
        heartbeat_thread.start()
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
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2)
        if server is not None:
            with suppress(Exception):
                server.server_close()
            if loop is not None and loop.is_running():
                with suppress(Exception):
                    server.run_agent(server.daemon.close())
        store.remove_daemon_record(instance_id=instance_id)
        _remove_session_if_instance(store, profile_id, instance_id)
        if loop is not None:
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            if loop_thread is not None:
                loop_thread.join(timeout=5)
            with suppress(Exception):
                loop.close()


def _run_agent_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _load_auth_token(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    token = data.get("token") if isinstance(data, dict) else None
    return str(token) if token else None


def _bind_agent_server(*, port_base: int, port_count: int) -> AgentHTTPServer:
    last_error: OSError | None = None
    for port in agent_ports(port_base=port_base, port_count=port_count):
        try:
            return AgentHTTPServer((AGENT_HOST, port), AgentRequestHandler)
        except OSError as exc:
            last_error = exc
    raise RuntimeError(
        f"Could not bind Rotunda agent on {AGENT_HOST}:{port_base}-{port_base + port_count - 1}"
    ) from last_error


def _heartbeat_daemon_state(
    store: AgentStore,
    profile_id: str,
    session_file: Path,
    session: dict[str, Any],
    server: AgentHTTPServer,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        session["update_tick"] = time.time()
        server.update_tick = float(session["update_tick"])
        with suppress(Exception):
            _write_daemon_state(store, profile_id, session_file, session)


def _write_daemon_state(
    store: AgentStore,
    profile_id: str,
    session_file: Path,
    session: dict[str, Any],
) -> None:
    store.save_session(profile_id, session)
    if session_file != store.session_path(profile_id):
        store._atomic_write_json(session_file, session)
    store.save_daemon_record(
        {
            "service": AGENT_IDENTITY_SERVICE,
            "profile_id": session["profile_id"],
            "host": session["host"],
            "port": session["port"],
            "pid": session["pid"],
            "started_at": session["started_at"],
            "instance_id": session["instance_id"],
            "update_tick": session["update_tick"],
        }
    )


def _remove_session_if_instance(store: AgentStore, profile_id: str, instance_id: str) -> None:
    session = store.load_session(profile_id)
    if session and session.get("instance_id") == instance_id:
        store.remove_session(profile_id)


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
