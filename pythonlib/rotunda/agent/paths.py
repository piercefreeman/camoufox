from __future__ import annotations

from pathlib import Path

AGENT_HOME = Path.home() / ".rotunda" / "agent"
PROFILES_DIR = AGENT_HOME / "profiles"
SESSIONS_DIR = AGENT_HOME / "sessions"
LOGS_DIR = AGENT_HOME / "logs"
RESOURCES_FILE = AGENT_HOME / "resources.json"


def ensure_agent_dirs() -> None:
    AGENT_HOME.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
