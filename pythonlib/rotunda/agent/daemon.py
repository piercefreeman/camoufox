from __future__ import annotations

import json
import os
import signal
import time
import uuid
from contextlib import suppress
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, cast

import rich_click as click
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .dom_serializer import DOMSerializer
from .store import AgentStore


class AgentDaemon:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.context_id: str | None = None
        self.pages: dict[str, Page] = {}
        self.page_serializers: dict[str, DOMSerializer] = {}

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

    def list_page(self, page_id: str, max_items: int = 200) -> dict[str, Any]:
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

    def click(self, page_id: str, ref: str) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        locator.click(timeout=15_000)
        self._settle(page)
        return self.list_page(page_id)

    def enter(self, page_id: str, ref: str, text: str, *, submit: bool = False) -> dict[str, Any]:
        page = self._page(page_id)
        serializer = self._serializer_for(page_id, page)
        locator = serializer.resolve_locator(page, ref)
        try:
            locator.fill(text, timeout=15_000)
        except Exception:
            locator.click(timeout=15_000)
            page.keyboard.type(text)
        if submit:
            locator.press("Enter")
        self._settle(page)
        return self.list_page(page_id)

    def _ensure_context(self) -> BrowserContext:
        if self.context:
            return self.context

        user_data_dir = Path(str(self.profile["user_data_dir"]))
        user_data_dir.mkdir(parents=True, exist_ok=True)
        headless = bool(self.profile.get("headless", True))
        executable_path = resolve_installed_rotunda_executable()

        self.playwright = sync_playwright().start()
        from rotunda.utils import launch_options

        opts = launch_options(
            headless=headless,
            executable_path=executable_path,
            env=dict(os.environ),
        )
        self.context = self.playwright.firefox.launch_persistent_context(
            str(user_data_dir),
            **opts,
        )

        self.context_id = f"ctx_{uuid.uuid4().hex[:10]}"
        self._adopt_pages(self.context.pages)
        if not self.pages:
            page = self.context.new_page()
            self._register_page(page)
        return self.context

    def _adopt_pages(self, pages: list[Page]) -> None:
        known = set(self.pages.values())
        for page in pages:
            if page not in known:
                self._register_page(page)

    def _register_page(self, page: Page) -> str:
        page_id = f"page_{uuid.uuid4().hex[:10]}"
        self.pages[page_id] = page
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

    def _page_payload(self, page_id: str, page: Page) -> dict[str, str]:
        try:
            title = page.title()
        except Exception:
            title = ""
        return {"id": page_id, "url": page.url, "title": title}


class AgentHTTPServer(ThreadingHTTPServer):
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
            elif self.path == "/navigate":
                wait_until = _wait_until(str(payload.get("wait_until") or "domcontentloaded"))
                result = self.server.daemon.navigate(
                    str(payload["page_id"]),
                    str(payload["url"]),
                    wait_until,
                )
            elif self.path == "/list":
                result = self.server.daemon.list_page(
                    str(payload["page_id"]),
                    int(payload.get("max_items") or 200),
                )
            elif self.path == "/click":
                result = self.server.daemon.click(str(payload["page_id"]), str(payload["ref"]))
            elif self.path == "/enter":
                result = self.server.daemon.enter(
                    str(payload["page_id"]),
                    str(payload["ref"]),
                    str(payload["text"]),
                    submit=bool(payload.get("submit", False)),
                )
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

def _wait_until(value: str) -> Literal["commit", "domcontentloaded", "load", "networkidle"]:
    if value in {"commit", "domcontentloaded", "load", "networkidle"}:
        return cast(Literal["commit", "domcontentloaded", "load", "networkidle"], value)
    raise ValueError(f"Unsupported wait_until value: {value}")


if __name__ == "__main__":
    main()
