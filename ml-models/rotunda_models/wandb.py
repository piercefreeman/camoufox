"""Optional Weights & Biases integration for cadence training."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Any

from .types import WandbState
from .utils import jsonable


def parse_wandb_tags(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_tags = value.split(",")
    else:
        raw_tags = []
        for item in value:
            raw_tags.extend(str(item).split(","))
    return [tag.strip() for tag in raw_tags if tag.strip()]


def wandb_requested(args: argparse.Namespace) -> bool:
    if getattr(args, "wandb_mode", None) == "disabled":
        return False
    return bool(
        getattr(args, "wandb", False)
        or getattr(args, "wandb_project", None)
        or getattr(args, "wandb_entity", None)
        or getattr(args, "wandb_run_name", None)
        or getattr(args, "wandb_group", None)
        or getattr(args, "wandb_mode", None) in {"online", "offline"}
        or parse_wandb_tags(getattr(args, "wandb_tags", None))
    )


def import_wandb():
    try:
        import wandb  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "W&B tracking requested, but the 'wandb' package is not installed. "
            "Install it with: python3 -m pip install wandb"
        ) from exc
    return wandb


def start_wandb_run(
    args: argparse.Namespace,
    task: str,
    run_dir: Path,
    config: dict,
    metadata: dict[str, Any],
) -> WandbState | None:
    if not wandb_requested(args):
        return None

    wandb = import_wandb()
    run_config = {
        **config,
        "task": task,
        "run_dir": str(run_dir),
        **{key: jsonable(value) for key, value in metadata.items()},
    }
    active_run = getattr(wandb, "run", None)
    if active_run is None:
        run = wandb.init(
            project=getattr(args, "wandb_project", None),
            entity=getattr(args, "wandb_entity", None),
            name=getattr(args, "wandb_run_name", None),
            group=getattr(args, "wandb_group", None),
            tags=parse_wandb_tags(getattr(args, "wandb_tags", None)) or None,
            mode=getattr(args, "wandb_mode", None),
            config=run_config,
        )
        owns_run = True
    else:
        run = active_run
        run.config.update(run_config, allow_val_change=True)
        owns_run = False

    wandb.define_metric("epoch")
    for prefix in ("train", "val", "score", "best"):
        wandb.define_metric(f"{prefix}/*", step_metric="epoch")

    run.summary["task"] = task
    run.summary["run_dir"] = str(run_dir)
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool) or value is None:
            run.summary[key] = value
    return WandbState(module=wandb, run=run, owns_run=owns_run)


def finish_wandb_run(state: WandbState | None) -> None:
    if state is not None and state.owns_run:
        state.run.finish()


def wandb_log_epoch(
    state: WandbState | None,
    epoch: int,
    train_metrics: dict[str, float],
    val_metrics: dict[str, float],
    score: float,
    best_score: float,
    best_epoch: int,
    lr: float | None,
) -> None:
    if state is None:
        return
    payload: dict[str, Any] = {"epoch": epoch, "score/loss": score}
    payload.update({f"train/{key}": value for key, value in train_metrics.items()})
    payload.update({f"val/{key}": value for key, value in val_metrics.items()})
    if math.isfinite(best_score):
        payload["best/loss"] = best_score
        payload["best/epoch"] = best_epoch
    if lr is not None:
        payload["optimizer/lr"] = lr
    state.run.log(payload, step=epoch)


def wandb_log_artifacts(state: WandbState | None, task: str, run_dir: Path) -> None:
    if state is None:
        return
    artifact_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{task}-{run_dir.name}-checkpoints")
    artifact = state.module.Artifact(artifact_name, type="model")
    for filename in ("model-best.pt", "model.pt", "metrics.jsonl"):
        path = run_dir / filename
        if path.exists():
            artifact.add_file(str(path), name=filename)
    state.run.log_artifact(artifact)
