from __future__ import annotations

import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import PROFILES_DIR, RESOURCES_FILE, SESSIONS_DIR, ensure_agent_dirs


@dataclass(frozen=True, slots=True)
class AgentResource:
    idx: int
    kind: str
    id: str
    profile_id: str | None = None
    parent_id: str | None = None
    label: str = ""
    created_at: float = 0.0


class AgentStore:
    def __init__(self) -> None:
        ensure_agent_dirs()

    def create_profile(
        self,
        *,
        name: str | None = None,
        headless: bool = False,
    ) -> dict[str, Any]:
        profile_id = f"prof_{uuid.uuid4().hex[:12]}"
        profile_dir = PROFILES_DIR / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile = {
            "id": profile_id,
            "name": name or profile_id,
            "browser": "rotunda",
            "headless": headless,
            "humanize": True,
            "created_at": time.time(),
            "profile_dir": str(profile_dir),
            "user_data_dir": str(profile_dir / "browser-data"),
        }
        self.save_profile(profile)
        return profile

    def load_profile(self, profile_id: str) -> dict[str, Any]:
        path = self.profile_path(profile_id)
        if not path.exists():
            raise KeyError(f"Unknown profile: {profile_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_profile(self, profile: dict[str, Any]) -> None:
        path = self.profile_path(str(profile["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")

    def profile_path(self, profile_id: str) -> Path:
        return PROFILES_DIR / profile_id / "profile.json"

    def session_path(self, profile_id: str) -> Path:
        return SESSIONS_DIR / f"{profile_id}.json"

    def load_session(self, profile_id: str) -> dict[str, Any] | None:
        path = self.session_path(profile_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def save_session(self, profile_id: str, session: dict[str, Any]) -> None:
        path = self.session_path(profile_id)
        path.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

    def remove_session(self, profile_id: str) -> None:
        path = self.session_path(profile_id)
        if path.exists():
            path.unlink()

    def new_token(self) -> str:
        return secrets.token_urlsafe(24)

    def register(
        self,
        *,
        kind: str,
        id: str,
        profile_id: str | None = None,
        parent_id: str | None = None,
        label: str = "",
    ) -> AgentResource:
        state = self._load_resources()
        for raw in state["resources"]:
            if raw["kind"] == kind and raw["id"] == id:
                raw.update(
                    {
                        "profile_id": profile_id,
                        "parent_id": parent_id,
                        "label": label,
                    }
                )
                self._save_resources(state)
                return AgentResource(**raw)

        idx = int(state["next_idx"])
        state["next_idx"] = idx + 1
        raw = {
            "idx": idx,
            "kind": kind,
            "id": id,
            "profile_id": profile_id,
            "parent_id": parent_id,
            "label": label,
            "created_at": time.time(),
        }
        state["resources"].append(raw)
        self._save_resources(state)
        return AgentResource(**raw)

    def remove_children(self, parent_id: str, *, kind: str | None = None) -> None:
        state = self._load_resources()
        original_count = len(state["resources"])
        state["resources"] = [
            raw
            for raw in state["resources"]
            if not (raw.get("parent_id") == parent_id and (kind is None or raw.get("kind") == kind))
        ]
        if len(state["resources"]) != original_count:
            self._save_resources(state)

    def resolve(self, ref: str | None, *, kind: str | None = None) -> AgentResource:
        state = self._load_resources()
        resources = [AgentResource(**raw) for raw in state["resources"]]
        if not ref:
            matches = [resource for resource in resources if kind is None or resource.kind == kind]
            if not matches:
                raise KeyError(f"No {kind or 'resource'} has been created")
            return max(matches, key=lambda resource: resource.idx)

        if ref.isdigit():
            for resource in resources:
                if resource.idx == int(ref) and (kind is None or resource.kind == kind):
                    return resource
        for resource in resources:
            if resource.id == ref and (kind is None or resource.kind == kind):
                return resource

        expected = f" {kind}" if kind else ""
        raise KeyError(f"Unknown{expected} reference: {ref}")

    def list_resources(self, *, kind: str | None = None) -> list[AgentResource]:
        state = self._load_resources()
        resources = [AgentResource(**raw) for raw in state["resources"]]
        if kind:
            return [resource for resource in resources if resource.kind == kind]
        return resources

    def _load_resources(self) -> dict[str, Any]:
        if not RESOURCES_FILE.exists():
            return {"next_idx": 1, "resources": []}
        try:
            data = json.loads(RESOURCES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"next_idx": 1, "resources": []}
        data.setdefault("next_idx", 1)
        data.setdefault("resources", [])
        return data

    def _save_resources(self, state: dict[str, Any]) -> None:
        RESOURCES_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
