from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .paths import LOGS_DIR
from .store import AgentStore


class AgentClientError(RuntimeError):
    pass


class AgentClient:
    def __init__(self, session: dict[str, Any]) -> None:
        self.session = session
        self.base_url = f"http://{session['host']}:{session['port']}"
        self.token = str(session["token"])

    def get(self, path: str) -> dict[str, Any]:
        request = Request(
            self.base_url + path,
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        return self._open(request)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload or {}).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._open(request)

    def ping(self) -> bool:
        try:
            self.get("/ping")
            return True
        except Exception:
            return False

    def _open(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(detail)
                message = parsed.get("error") or detail
            except json.JSONDecodeError:
                message = detail or str(exc)
            raise AgentClientError(message) from None
        except URLError as exc:
            raise AgentClientError(str(exc.reason)) from None

        if not data.get("ok", False):
            raise AgentClientError(str(data.get("error") or "Agent command failed"))
        return data


def ensure_daemon(profile_id: str, *, store: AgentStore | None = None) -> AgentClient:
    store = store or AgentStore()
    session = store.load_session(profile_id)
    if session:
        client = AgentClient(session)
        if client.ping():
            return client
        store.remove_session(profile_id)

    session = _start_daemon(profile_id, store=store)
    client = AgentClient(session)
    if not client.ping():
        raise AgentClientError("Agent daemon started but did not respond")
    return client


def _start_daemon(profile_id: str, *, store: AgentStore) -> dict[str, Any]:
    token = store.new_token()
    ready_file = LOGS_DIR / f"{profile_id}-{int(time.time())}.ready.json"
    log_file = LOGS_DIR / f"{profile_id}.log"
    session_file = store.session_path(profile_id)

    command = [
        sys.executable,
        "-m",
        "rotunda.agent.daemon",
        "--profile-id",
        profile_id,
        "--token",
        token,
        "--ready-file",
        str(ready_file),
        "--session-file",
        str(session_file),
    ]
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    with log_file.open("ab") as log:
        subprocess.Popen(  # nosec - launches this package's local agent daemon.
            command,
            cwd=Path.cwd(),
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    deadline = time.time() + 30
    while time.time() < deadline:
        if ready_file.exists():
            data = json.loads(ready_file.read_text(encoding="utf-8"))
            if data.get("ok"):
                return data["session"]
            raise AgentClientError(str(data.get("error") or "Agent daemon failed to start"))
        time.sleep(0.1)

    raise AgentClientError(f"Timed out starting agent daemon; see {log_file}")
