from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

DOM_SERIALIZER_SCRIPT = r"""
(options) => {
  const config = {
    includeContent: options.includeContent !== false,
    includeInteractive: options.includeInteractive !== false,
    maxTextLength: options.maxTextLength || 140,
    maxItems: options.maxItems || 250,
  };

  const SKIP_TAGS = new Set([
    "script",
    "style",
    "template",
    "noscript",
    "meta",
    "link",
    "base",
    "head",
    "path",
    "defs",
  ]);

  const TEXT_TAGS = new Set([
    "address",
    "article",
    "blockquote",
    "caption",
    "code",
    "dd",
    "dt",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "label",
    "legend",
    "li",
    "p",
    "pre",
    "td",
    "th",
  ]);

  const INTERACTIVE_ROLES = new Set([
    "button",
    "checkbox",
    "combobox",
    "link",
    "listbox",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
    "treeitem",
  ]);

  const clean = (value) => {
    if (value == null) {
      return "";
    }
    return String(value)
      .replace(/[\uE000-\uF8FF]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  };

  const truncate = (value) => {
    const text = clean(value);
    if (text.length <= config.maxTextLength) {
      return text;
    }
    return text.slice(0, Math.max(0, config.maxTextLength - 1)).trimEnd() + "...";
  };

  const cssEscape = (value) => {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (char) => {
      return "\\" + char.charCodeAt(0).toString(16) + " ";
    });
  };

  const isHiddenByAttribute = (el) => {
    if (el.hidden || el.getAttribute("aria-hidden") === "true") {
      return true;
    }
    const type = (el.getAttribute("type") || "").toLowerCase();
    return el.tagName.toLowerCase() === "input" && type === "hidden";
  };

  const isVisible = (el) => {
    if (!(el instanceof Element) || isHiddenByAttribute(el)) {
      return false;
    }
    const style = window.getComputedStyle(el);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      style.visibility === "collapse" ||
      Number(style.opacity) === 0
    ) {
      return false;
    }
    const rects = Array.from(el.getClientRects());
    return rects.some((rect) => rect.width > 0 && rect.height > 0);
  };

  const tagName = (el) => el.tagName.toLowerCase();

  const explicitRole = (el) => clean(el.getAttribute("role")).toLowerCase();

  const inferredRole = (el) => {
    const tag = tagName(el);
    const role = explicitRole(el);
    if (role) {
      return role;
    }
    if (tag === "a" && el.hasAttribute("href")) {
      return "link";
    }
    if (tag === "button" || tag === "summary") {
      return "button";
    }
    if (tag === "select") {
      return "combobox";
    }
    if (tag === "textarea") {
      return "textbox";
    }
    if (tag === "iframe" || tag === "frame") {
      return "frame";
    }
    if (/^h[1-6]$/.test(tag)) {
      return "heading";
    }
    if (tag === "img") {
      return "image";
    }
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset"].includes(type)) {
        return "button";
      }
      if (["checkbox", "radio", "range"].includes(type)) {
        return type === "range" ? "slider" : type;
      }
      return "textbox";
    }
    return "";
  };

  const labelledByText = (el) => {
    const labelledBy = clean(el.getAttribute("aria-labelledby"));
    if (!labelledBy) {
      return "";
    }
    return labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id))
      .filter(Boolean)
      .map((node) => clean(node.textContent))
      .filter(Boolean)
      .join(" ");
  };

  const associatedLabelText = (el) => {
    if (!("labels" in el) || !el.labels) {
      return "";
    }
    return Array.from(el.labels)
      .map((label) => clean(label.textContent))
      .filter(Boolean)
      .join(" ");
  };

  const elementText = (el) => {
    const innerText = typeof el.innerText === "string" ? el.innerText : el.textContent;
    return truncate(innerText);
  };

  const accessibleName = (el) => {
    const tag = tagName(el);
    const ariaLabel = clean(el.getAttribute("aria-label"));
    const labelledBy = labelledByText(el);
    if (ariaLabel) {
      return truncate(ariaLabel);
    }
    if (labelledBy) {
      return truncate(labelledBy);
    }
    const labelText = associatedLabelText(el);
    if (labelText) {
      return truncate(labelText);
    }
    if (tag === "img") {
      return truncate(el.getAttribute("alt") || el.getAttribute("title") || "");
    }
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset"].includes(type)) {
        return truncate(el.getAttribute("value") || type);
      }
      return truncate(el.getAttribute("placeholder") || el.getAttribute("title") || "");
    }
    return truncate(el.getAttribute("title") || elementText(el));
  };

  const isDisabled = (el) => {
    return Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true";
  };

  const isInteractive = (el) => {
    const tag = tagName(el);
    const role = inferredRole(el);
    if (INTERACTIVE_ROLES.has(role)) {
      return true;
    }
    if (
      ["button", "select", "textarea", "summary", "label"].includes(tag) ||
      (tag === "a" && el.hasAttribute("href")) ||
      (tag === "input" && (el.getAttribute("type") || "").toLowerCase() !== "hidden")
    ) {
      return true;
    }
    if (el.isContentEditable) {
      return true;
    }
    const tabindex = el.getAttribute("tabindex");
    if (tabindex != null && Number(tabindex) >= 0) {
      return true;
    }
    return typeof el.onclick === "function" || el.hasAttribute("onclick");
  };

  const hasUsefulText = (el) => {
    const text = elementText(el);
    return text.length > 0 && text !== accessibleName(el);
  };

  const shouldInclude = (el) => {
    const tag = tagName(el);
    if (SKIP_TAGS.has(tag)) {
      return false;
    }
    if (!isVisible(el)) {
      return false;
    }

    const interactive = isInteractive(el);
    if (config.includeInteractive && interactive) {
      return true;
    }
    if (!config.includeContent) {
      return false;
    }

    const role = inferredRole(el);
    const name = accessibleName(el);
    if (role && role !== "generic" && role !== "presentation" && name) {
      return true;
    }
    if (TEXT_TAGS.has(tag) && hasUsefulText(el)) {
      return true;
    }
    return tag === "iframe" && Boolean(name || el.getAttribute("src"));
  };

  const elementIndex = (el) => {
    const tag = tagName(el);
    let index = 1;
    let sibling = el.previousElementSibling;
    while (sibling) {
      if (tagName(sibling) === tag) {
        index += 1;
      }
      sibling = sibling.previousElementSibling;
    }
    return index;
  };

  const cssSegment = (el) => {
    const tag = tagName(el);
    const id = el.getAttribute("id");
    if (id && document.querySelectorAll("#" + cssEscape(id)).length === 1) {
      return tag + "#" + cssEscape(id);
    }
    return tag + ":nth-of-type(" + elementIndex(el) + ")";
  };

  const selectorPaths = (el) => {
    const cssParts = [];
    const xpathParts = [];
    let node = el;
    let sawShadow = false;

    while (node && node.nodeType === Node.ELEMENT_NODE) {
      const segment = cssSegment(node);
      cssParts.unshift("css=" + segment);

      const tag = tagName(node);
      const xpathName = tag.includes(":")
        ? "*[name()='" + tag.replace(/'/g, "\\'") + "']"
        : tag;
      xpathParts.unshift(xpathName + "[" + elementIndex(node) + "]");

      const root = node.getRootNode();
      if (root instanceof ShadowRoot) {
        sawShadow = true;
        node = root.host;
      } else {
        node = node.parentElement;
      }
    }

    return {
      css: cssParts.join(" >> "),
      xpath: "/" + xpathParts.join("/"),
      shadow: sawShadow,
    };
  };

  const boundsFor = (el) => {
    const rect = el.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  };

  const depthFor = (el) => {
    let depth = 0;
    let node = el.parentElement;
    while (node) {
      depth += 1;
      const root = node.getRootNode();
      if (root instanceof ShadowRoot) {
        node = root.host;
      } else {
        node = node.parentElement;
      }
    }
    return depth;
  };

  const attrsFor = (el) => {
    const attrs = {};
    for (const name of [
      "id",
      "name",
      "type",
      "role",
      "aria-label",
      "placeholder",
      "title",
      "alt",
      "href",
      "src",
      "value",
    ]) {
      const value = clean(el.getAttribute(name));
      if (value) {
        attrs[name] = truncate(value);
      }
    }
    if (el instanceof HTMLAnchorElement && el.href) {
      attrs.href = truncate(el.href);
    }
    if (el instanceof HTMLImageElement && el.currentSrc) {
      attrs.src = truncate(el.currentSrc);
    }
    if (el instanceof HTMLInputElement) {
      if (el.checked) {
        attrs.checked = "true";
      }
      if (el.value && !attrs.value && ["button", "submit", "reset"].includes(el.type)) {
        attrs.value = truncate(el.value);
      }
    }
    if (el instanceof HTMLOptionElement && el.selected) {
      attrs.selected = "true";
    }
    if (isDisabled(el)) {
      attrs.disabled = "true";
    }
    return attrs;
  };

  const items = [];
  const seen = new Set();

  const pushElement = (el) => {
    if (items.length >= config.maxItems || seen.has(el) || !shouldInclude(el)) {
      return;
    }
    seen.add(el);

    const role = inferredRole(el);
    const interactive = isInteractive(el);
    const paths = selectorPaths(el);
    const name = accessibleName(el);
    const text = elementText(el);
    const attrs = attrsFor(el);

    items.push({
      local_id: items.length,
      tag: tagName(el),
      role,
      name,
      text,
      attributes: attrs,
      xpath: paths.xpath,
      css: paths.css,
      shadow: paths.shadow,
      interactive,
      content: !interactive,
      disabled: isDisabled(el),
      bounds: boundsFor(el),
      depth: depthFor(el),
    });
  };

  const visit = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let node = root.nodeType === Node.ELEMENT_NODE ? root : walker.nextNode();
    while (node && items.length < config.maxItems) {
      pushElement(node);
      if (node.shadowRoot) {
        visit(node.shadowRoot);
      }
      node = walker.nextNode();
    }
  };

  visit(document.documentElement);
  return items;
}
"""


@dataclass(frozen=True, slots=True)
class DOMBounds:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DOMFrame:
    index: int
    url: str
    name: str = ""
    parent_index: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DOMElement:
    ref: str
    uuid: str
    frame_index: int
    frame_url: str
    frame_name: str
    local_id: int
    tag: str
    role: str
    name: str
    text: str
    attributes: dict[str, str]
    xpath: str
    css: str
    in_shadow_tree: bool
    interactive: bool
    content: bool
    disabled: bool
    bounds: DOMBounds | None
    depth: int

    def agent_line(self) -> str:
        kind = self.role or self.tag
        label = self.name or self.text
        attrs = self._agent_attributes()
        disabled = " disabled" if self.disabled else ""
        suffix = f" {' '.join(attrs)}" if attrs else ""
        if label:
            return f'[{self.ref}] - {kind}{disabled} "{_quote_inline(label)}"{suffix}'
        return f"[{self.ref}] - {kind}{disabled}{suffix}"

    def _agent_attributes(self) -> list[str]:
        attrs: list[str] = []
        if self.role and self.tag and self.tag != self.role:
            attrs.append(f"<{self.tag}>")

        for key in ("placeholder", "type", "href", "src", "title", "alt", "name", "id"):
            value = self.attributes.get(key)
            if not value:
                continue
            if key in {"title", "alt"} and value == self.name:
                continue
            if key in {"href", "src"}:
                value = _compact_url(value)
            attrs.append(f'{key}="{_quote_inline(value)}"')

        if self.in_shadow_tree:
            attrs.append("shadow=true")
        return attrs


@dataclass(frozen=True, slots=True)
class DOMSnapshot:
    items: list[DOMElement]
    frames: list[DOMFrame]
    text: str

    def __str__(self) -> str:
        return self.text

    def get(self, ref: str) -> DOMElement:
        for item in self.items:
            if item.ref == ref:
                return item
        raise KeyError(ref)


@dataclass(slots=True)
class DOMReference:
    element: DOMElement
    selectors: tuple[str, ...] = field(default_factory=tuple)


class DOMSerializer:
    """
    Convert a Playwright page into a compact, agent-readable DOM snapshot.

    The serializer walks every Playwright frame independently. That gives it
    access to same-origin and cross-origin iframes while keeping the visible
    representation small enough for model prompts. Each emitted element gets a
    short reference derived from a UUID, and the serializer keeps those
    references in memory so later CLI commands can resolve them back to selector
    candidates.
    """

    def __init__(
        self,
        *,
        max_items: int = 200,
        max_text_length: int = 140,
        hash_length: int = 8,
        include_content: bool = True,
        include_interactive: bool = True,
    ) -> None:
        if hash_length < 4:
            raise ValueError("hash_length must be at least 4")
        self.max_items = max_items
        self.max_text_length = max_text_length
        self.hash_length = hash_length
        self.include_content = include_content
        self.include_interactive = include_interactive
        self._identity_cache: dict[str, uuid.UUID] = {}
        self._ref_to_uuid: dict[str, uuid.UUID] = {}
        self._references: dict[str, DOMReference] = {}

    def serialize(self, page: Any) -> DOMSnapshot:
        frames = list(_read_attr(page, "frames", []))
        frame_index = {id(frame): index for index, frame in enumerate(frames)}
        dom_frames: list[DOMFrame] = []
        items: list[DOMElement] = []
        key_counts: dict[str, int] = {}

        for index, frame in enumerate(frames):
            url = str(_read_attr(frame, "url", "") or "")
            name = str(_read_attr(frame, "name", "") or "")
            parent = _read_attr(frame, "parent_frame", None)
            parent_index = frame_index.get(id(parent))

            try:
                raw_items = frame.evaluate(DOM_SERIALIZER_SCRIPT, self._script_options())
                dom_frames.append(DOMFrame(index=index, url=url, name=name, parent_index=parent_index))
            except Exception as exc:
                dom_frames.append(
                    DOMFrame(
                        index=index,
                        url=url,
                        name=name,
                        parent_index=parent_index,
                        error=str(exc),
                    )
                )
                continue

            for raw in raw_items:
                if len(items) >= self.max_items:
                    break
                element = self._element_from_raw(
                    raw=raw,
                    frame_index=index,
                    frame_url=url,
                    frame_name=name,
                    key_counts=key_counts,
                )
                items.append(element)
                self._references[element.ref] = DOMReference(
                    element=element,
                    selectors=tuple(
                        selector
                        for selector in (element.css, f"xpath={element.xpath}" if element.xpath else "")
                        if selector
                    ),
                )

        text = self.render(items, dom_frames)
        return DOMSnapshot(items=items, frames=dom_frames, text=text)

    async def async_serialize(self, page: Any) -> DOMSnapshot:
        frames = list(_read_attr(page, "frames", []))
        frame_index = {id(frame): index for index, frame in enumerate(frames)}
        dom_frames: list[DOMFrame] = []
        items: list[DOMElement] = []
        key_counts: dict[str, int] = {}

        for index, frame in enumerate(frames):
            url = str(_read_attr(frame, "url", "") or "")
            name = str(_read_attr(frame, "name", "") or "")
            parent = _read_attr(frame, "parent_frame", None)
            parent_index = frame_index.get(id(parent))

            try:
                raw_items = await frame.evaluate(DOM_SERIALIZER_SCRIPT, self._script_options())
                dom_frames.append(DOMFrame(index=index, url=url, name=name, parent_index=parent_index))
            except Exception as exc:
                dom_frames.append(
                    DOMFrame(
                        index=index,
                        url=url,
                        name=name,
                        parent_index=parent_index,
                        error=str(exc),
                    )
                )
                continue

            for raw in raw_items:
                if len(items) >= self.max_items:
                    break
                element = self._element_from_raw(
                    raw=raw,
                    frame_index=index,
                    frame_url=url,
                    frame_name=name,
                    key_counts=key_counts,
                )
                items.append(element)
                self._references[element.ref] = DOMReference(
                    element=element,
                    selectors=tuple(
                        selector
                        for selector in (element.css, f"xpath={element.xpath}" if element.xpath else "")
                        if selector
                    ),
                )

        text = self.render(items, dom_frames)
        return DOMSnapshot(items=items, frames=dom_frames, text=text)

    def get_reference(self, ref: str) -> DOMReference:
        try:
            return self._references[ref]
        except KeyError:
            raise KeyError(f"Unknown DOM reference: {ref}") from None

    def resolve_locator(self, page: Any, ref: str) -> Any:
        reference = self.get_reference(ref)
        frame = _frame_for_reference(page, reference)

        last_error: Exception | None = None
        for selector in reference.selectors:
            try:
                locator = frame.locator(selector)
                if locator.count() > 0:
                    return locator.first
            except Exception as exc:
                last_error = exc

        if last_error:
            raise KeyError(f"Unable to resolve DOM reference {ref}: {last_error}") from None
        raise KeyError(f"Unable to resolve DOM reference: {ref}") from None

    async def async_resolve_locator(self, page: Any, ref: str) -> Any:
        reference = self.get_reference(ref)
        frame = _frame_for_reference(page, reference)

        last_error: Exception | None = None
        for selector in reference.selectors:
            try:
                locator = frame.locator(selector)
                if await locator.count() > 0:
                    return locator.first
            except Exception as exc:
                last_error = exc

        if last_error:
            raise KeyError(f"Unable to resolve DOM reference {ref}: {last_error}") from None
        raise KeyError(f"Unable to resolve DOM reference: {ref}") from None

    def render(self, items: list[DOMElement], frames: list[DOMFrame]) -> str:
        if not items:
            return ""

        lines: list[str] = []
        multi_frame = len(frames) > 1
        frames_by_index = {frame.index: frame for frame in frames}
        current_frame_index: int | None = None

        for item in items:
            if multi_frame and item.frame_index != current_frame_index:
                current_frame_index = item.frame_index
                frame = frames_by_index.get(item.frame_index)
                if frame:
                    label = f"Frame {frame.index}"
                    if frame.name:
                        label += f' "{_quote_inline(frame.name)}"'
                    if frame.url:
                        label += f": {_compact_url(frame.url)}"
                    if frame.error:
                        label += f" (unavailable: {_quote_inline(frame.error)})"
                    lines.append(label)
            lines.append(item.agent_line())

        return "\n".join(lines)

    def clear_references(self) -> None:
        self._references.clear()

    def _script_options(self) -> dict[str, Any]:
        return {
            "includeContent": self.include_content,
            "includeInteractive": self.include_interactive,
            "maxItems": self.max_items,
            "maxTextLength": self.max_text_length,
        }

    def _element_from_raw(
        self,
        *,
        raw: dict[str, Any],
        frame_index: int,
        frame_url: str,
        frame_name: str,
        key_counts: dict[str, int],
    ) -> DOMElement:
        attributes = {str(key): str(value) for key, value in (raw.get("attributes") or {}).items()}
        base_key = self._stable_key(raw=raw, frame_index=frame_index, frame_url=frame_url)
        occurrence = key_counts.get(base_key, 0)
        key_counts[base_key] = occurrence + 1
        stable_key = f"{base_key}#{occurrence}"
        element_uuid = self._identity_cache.setdefault(stable_key, uuid.uuid4())
        ref = self._short_ref(element_uuid)
        bounds = _bounds_from_raw(raw.get("bounds"))

        return DOMElement(
            ref=ref,
            uuid=str(element_uuid),
            frame_index=frame_index,
            frame_url=frame_url,
            frame_name=frame_name,
            local_id=int(raw.get("local_id") or 0),
            tag=str(raw.get("tag") or ""),
            role=str(raw.get("role") or ""),
            name=str(raw.get("name") or ""),
            text=str(raw.get("text") or ""),
            attributes=attributes,
            xpath=str(raw.get("xpath") or ""),
            css=str(raw.get("css") or ""),
            in_shadow_tree=bool(raw.get("shadow")),
            interactive=bool(raw.get("interactive")),
            content=bool(raw.get("content")),
            disabled=bool(raw.get("disabled")),
            bounds=bounds,
            depth=int(raw.get("depth") or 0),
        )

    def _stable_key(self, *, raw: dict[str, Any], frame_index: int, frame_url: str) -> str:
        attrs = raw.get("attributes") or {}
        strong_attrs = {
            key: attrs.get(key)
            for key in ("id", "name", "type", "role", "aria-label", "placeholder", "href", "src", "alt", "title")
            if attrs.get(key)
        }
        semantic = {
            "frame_index": frame_index,
            "frame_url": frame_url.split("#", 1)[0],
            "tag": raw.get("tag") or "",
            "role": raw.get("role") or "",
            "name": raw.get("name") or "",
            "strong_attrs": strong_attrs,
        }
        if not semantic["name"] and not strong_attrs:
            semantic["xpath"] = raw.get("xpath") or ""
            semantic["css"] = raw.get("css") or ""
            semantic["local_id"] = raw.get("local_id") or 0
        payload = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2s(payload.encode("utf-8"), digest_size=16).hexdigest()

    def _short_ref(self, element_uuid: uuid.UUID) -> str:
        digest = base64.b32encode(
            hashlib.blake2s(element_uuid.bytes, digest_size=8).digest()
        ).decode("ascii").lower().rstrip("=")
        for length in range(self.hash_length, len(digest) + 1):
            ref = digest[:length]
            existing = self._ref_to_uuid.get(ref)
            if existing is None or existing == element_uuid:
                self._ref_to_uuid[ref] = element_uuid
                return ref
        ref = digest
        self._ref_to_uuid[ref] = element_uuid
        return ref


def _read_attr(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    if callable(value):
        try:
            return value()
        except TypeError:
            return value
    return value


def _bounds_from_raw(raw: Any) -> DOMBounds | None:
    if not isinstance(raw, dict):
        return None
    return DOMBounds(
        x=int(raw.get("x") or 0),
        y=int(raw.get("y") or 0),
        width=int(raw.get("width") or 0),
        height=int(raw.get("height") or 0),
    )


def _frame_for_reference(page: Any, reference: DOMReference) -> Any:
    frames = list(_read_attr(page, "frames", []))
    element = reference.element
    if element.frame_index < len(frames):
        frame = frames[element.frame_index]
        if _frame_matches_element(frame, element):
            return frame

    for frame in frames:
        if _frame_matches_element(frame, element):
            return frame

    if element.frame_index < len(frames):
        return frames[element.frame_index]
    raise KeyError(f"Frame no longer exists for DOM reference: {element.ref}") from None


def _frame_matches_element(frame: Any, element: DOMElement) -> bool:
    url = str(_read_attr(frame, "url", "") or "").split("#", 1)[0]
    expected_url = element.frame_url.split("#", 1)[0]
    name = str(_read_attr(frame, "name", "") or "")
    if expected_url and url != expected_url:
        return False
    return not element.frame_name or name == element.frame_name


def _compact_url(value: str, *, limit: int = 72) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _quote_inline(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
