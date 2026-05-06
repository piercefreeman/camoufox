from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .paths import AUTH_FILE, LOCK_FILE, LOGS_DIR
from .runtime import (
    AGENT_HOST,
    AGENT_IDENTITY_SERVICE,
    AGENT_PORT_BASE,
    AGENT_PORT_COUNT,
    agent_ports,
)
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


def discover_daemon(*, store: AgentStore | None = None) -> AgentClient | None:
    store = store or AgentStore()
    token = store.ensure_auth_token()
    session = _discover_daemon(token, store=store)
    return AgentClient(session) if session else None


def ensure_daemon(profile_id: str, *, store: AgentStore | None = None) -> AgentClient:
    store = store or AgentStore()
    token = store.ensure_auth_token()

    with _startup_lock():
        session = _discover_daemon(token, store=store)
        if session:
            if session.get("profile_id") == profile_id:
                store.save_session(profile_id, session)
                return AgentClient(session)
            _shutdown_session(session)
            _wait_for_daemon_exit(session)
            store.clear_runtime_state()

        store.clear_runtime_state()
        session = _start_daemon(profile_id, store=store)

    client = AgentClient(session)
    if not client.ping():
        raise AgentClientError("Agent daemon started but did not respond")
    return client


def _start_daemon(profile_id: str, *, store: AgentStore) -> dict[str, Any]:
    ready_file = LOGS_DIR / f"{profile_id}-{int(time.time())}-{uuid.uuid4().hex[:8]}.ready.json"
    log_file = LOGS_DIR / f"{profile_id}.log"
    session_file = store.session_path(profile_id)

    command = [
        sys.executable,
        "-m",
        "rotunda.agent.daemon",
        "--profile-id",
        profile_id,
        "--token-file",
        str(AUTH_FILE),
        "--ready-file",
        str(ready_file),
        "--session-file",
        str(session_file),
        "--port-base",
        str(AGENT_PORT_BASE),
        "--port-count",
        str(AGENT_PORT_COUNT),
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


def _discover_daemon(token: str, *, store: AgentStore) -> dict[str, Any] | None:
    seen_ports: set[int] = set()
    candidate_ports: list[int] = []
    record = store.load_daemon_record()
    if record and store.daemon_record_is_fresh(record):
        record_port = record.get("port")
        if record_port is not None:
            with suppress(TypeError, ValueError):
                candidate_ports.append(int(record_port))
    candidate_ports.extend(agent_ports())

    for port in candidate_ports:
        if port in seen_ports:
            continue
        seen_ports.add(port)
        identity = _fetch_identity(port)
        if identity is None:
            continue
        if identity.get("service") != AGENT_IDENTITY_SERVICE:
            continue
        session = _session_from_identity(identity, token=token, port=port)
        try:
            AgentClient(session).get("/ping")
        except AgentClientError as exc:
            raise AgentClientError(
                f"Rotunda agent on {AGENT_HOST}:{port} rejected this user's auth token: {exc}"
            ) from None
        store.save_daemon_record(_daemon_record_from_session(session))
        store.save_session(str(session["profile_id"]), session)
        return session
    return None


def _fetch_identity(port: int) -> dict[str, Any] | None:
    request = Request(f"http://{AGENT_HOST}:{port}/identity", method="GET")
    try:
        with urlopen(request, timeout=0.5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("ok") else None


def _session_from_identity(identity: dict[str, Any], *, token: str, port: int) -> dict[str, Any]:
    return {
        "profile_id": str(identity["profile_id"]),
        "host": AGENT_HOST,
        "port": port,
        "token": token,
        "pid": identity.get("pid"),
        "started_at": identity.get("started_at"),
        "instance_id": identity.get("instance_id"),
        "update_tick": identity.get("update_tick"),
    }


def _daemon_record_from_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "service": AGENT_IDENTITY_SERVICE,
        "profile_id": session.get("profile_id"),
        "host": session.get("host"),
        "port": session.get("port"),
        "pid": session.get("pid"),
        "started_at": session.get("started_at"),
        "instance_id": session.get("instance_id"),
        "update_tick": session.get("update_tick"),
    }


def _shutdown_session(session: dict[str, Any]) -> None:
    with suppress(Exception):
        AgentClient(session).post("/shutdown")


def _wait_for_daemon_exit(session: dict[str, Any]) -> None:
    port = int(session["port"])
    instance_id = session.get("instance_id")
    deadline = time.time() + 10
    while time.time() < deadline:
        identity = _fetch_identity(port)
        if identity is None or identity.get("instance_id") != instance_id:
            return
        time.sleep(0.1)


@contextmanager
def _startup_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            with suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            with suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
