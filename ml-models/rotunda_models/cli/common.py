"""Shared Click CLI helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click

PATH_TYPE = click.Path(path_type=Path)
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def namespace(**values: Any) -> SimpleNamespace:
    """Return the flat attribute object expected by existing model handlers."""
    return SimpleNamespace(**values)

