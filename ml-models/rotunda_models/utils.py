"""I/O, logging, timing, and geometry helpers for cadence models."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.text import Text

console = Console(highlight=False, soft_wrap=True)


def log_labeled(label: str, message: str, style: str = "cyan") -> None:
    text = Text()
    text.append(f"[{label}] ", style=style)
    text.append(str(message))
    console.print(text)


def log_stage(message: str) -> None:
    log_labeled("stage", message, "bold cyan")


def log_info(message: str) -> None:
    log_labeled("info", message, "dim")


def log_epoch(epoch: int, train_loss: float, val_loss: float | None = None) -> None:
    message = f"train_loss={train_loss:.4f}"
    if val_loss is not None:
        message += f" val_loss={val_loss:.4f}"
    log_labeled(f"epoch {epoch:03d}", message, "green")


def discover_recording_paths(inputs: list[str]) -> list[Path]:
    roots = [Path(item) for item in inputs] if inputs else [Path("recordings")]
    paths: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() in {".ndjson", ".jsonl"}:
            paths.append(root)
        elif root.is_dir():
            paths.extend(sorted(root.rglob("*.ndjson")))
            paths.extend(sorted(root.rglob("*.jsonl")))
    return sorted(set(paths))


def iter_events(paths: Iterable[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield path, line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc


def as_float(value, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def as_int(value, default: int | None = None) -> int | None:
    if value is None:
        return default
    return int(value)


def write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def jsonable(value):
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump())
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return str(value)


def namespace_config(args: argparse.Namespace) -> dict:
    return {
        key: jsonable(value)
        for key, value in vars(args).items()
        if key != "func"
    }


def make_run_dir(base: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = base / f"{prefix}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def dt_to_log(dt_ms: float) -> float:
    return math.log1p(max(0.0, float(dt_ms)))


def log_to_dt(value: float) -> float:
    return math.expm1(max(0.0, min(float(value), math.log1p(5000.0))))


def goal_relative_position(
    start_x: float,
    start_y: float,
    dst_x: float,
    dst_y: float,
    x: float,
    y: float,
) -> tuple[float, float]:
    dx = dst_x - start_x
    dy = dst_y - start_y
    distance = max(1.0, math.hypot(dx, dy))
    ux = dx / distance
    uy = dy / distance
    vx = -uy
    vy = ux
    rel_x = x - start_x
    rel_y = y - start_y
    along = ((rel_x * ux) + (rel_y * uy)) / distance
    perp = ((rel_x * vx) + (rel_y * vy)) / distance
    return along, perp


def screen_position_from_goal_relative(
    start_x: float,
    start_y: float,
    dst_x: float,
    dst_y: float,
    along: float,
    perp: float,
) -> tuple[float, float]:
    dx = dst_x - start_x
    dy = dst_y - start_y
    distance = max(1.0, math.hypot(dx, dy))
    ux = dx / distance
    uy = dy / distance
    vx = -uy
    vy = ux
    x = start_x + distance * ((along * ux) + (perp * vx))
    y = start_y + distance * ((along * uy) + (perp * vy))
    return x, y
