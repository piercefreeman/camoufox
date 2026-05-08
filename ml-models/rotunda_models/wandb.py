"""Optional Weights & Biases integration for cadence training."""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any

from .types import WandbState
from .utils import jsonable


def parse_wandb_tags(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize comma-separated or repeated W&B tag values."""
    if value is None:
        return []
    if isinstance(value, str):
        raw_tags = value.split(",")
    else:
        raw_tags = []
        for item in value:
            raw_tags.extend(str(item).split(","))
    return [tag.strip() for tag in raw_tags if tag.strip()]


def wandb_requested(args: Any) -> bool:
    """Return whether namespace settings request W&B integration."""
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
    """Import wandb or fail with a CLI-friendly installation message."""
    def is_sdk(module: Any) -> bool:
        return callable(getattr(module, "init", None)) and hasattr(module, "Table")

    try:
        import wandb  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "W&B tracking requested, but the 'wandb' package is not installed. "
            "Install it with: python3 -m pip install wandb"
        ) from exc
    if is_sdk(wandb):
        return wandb

    shadow_path = getattr(wandb, "__file__", None) or getattr(wandb, "__path__", None)
    repo_root = Path(__file__).resolve().parents[2]
    original_path = list(sys.path)
    sys.modules.pop("wandb", None)
    try:
        sys.path = [
            entry
            for entry in original_path
            if Path(entry or ".").resolve() != repo_root
        ]
        import wandb as sdk_wandb  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "W&B tracking requested, but the real 'wandb' SDK is not installed. "
            f"The initial import resolved to {shadow_path!s}. "
            "Install it with: python3 -m pip install wandb"
        ) from exc
    finally:
        sys.path = original_path
    if not is_sdk(sdk_wandb):
        resolved_path = getattr(sdk_wandb, "__file__", None) or getattr(sdk_wandb, "__path__", None)
        raise SystemExit(
            "W&B tracking requested, but 'import wandb' did not resolve to the SDK. "
            f"Resolved module: {resolved_path!s}"
        )
    wandb = sdk_wandb
    return wandb


def start_wandb_run(
    args: Any,
    task: str,
    run_dir: Path,
    config: dict,
    metadata: dict[str, Any],
) -> WandbState | None:
    """Start or reuse a W&B run for one training task."""
    if not wandb_requested(args):
        return None

    wandb = import_wandb()
    # Store run metadata in config so sweeps and ad hoc runs expose the same
    # training inputs, task identity, and extracted-corpus counts.
    run_config = {
        **config,
        "task": task,
        "run_dir": str(run_dir),
        **{key: jsonable(value) for key, value in metadata.items()},
    }
    active_run = getattr(wandb, "run", None)
    if active_run is None:
        # Normal CLI training owns its run and is responsible for finishing it.
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
        # Sweep agents usually create the run before calling into training; in
        # that case just enrich the active config.
        run = active_run
        run.config.update(run_config, allow_val_change=True)
        owns_run = False

    wandb.define_metric("epoch")
    for prefix in ("train", "val", "score", "best"):
        wandb.define_metric(f"{prefix}/*", step_metric="epoch")
    wandb.define_metric("keyboard_inspect/*", step_metric="epoch")

    run.summary["task"] = task
    run.summary["run_dir"] = str(run_dir)
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool) or value is None:
            run.summary[key] = value
    return WandbState(module=wandb, run=run, owns_run=owns_run)


def finish_wandb_run(state: WandbState | None) -> None:
    """Finish a W&B run only when this process created it."""
    if state is not None and state.owns_run:
        state.run.finish()


def wandb_log_epoch(
    state: WandbState | None,
    epoch: int,
    train_metrics: dict[str, float],
    val_metrics: dict[str, float],
    score: float,
    score_metrics: dict[str, float],
    best_score: float,
    best_composite_score: float | None,
    best_epoch: int,
    lr: float | None,
) -> None:
    """Log one epoch of train/validation metrics to W&B."""
    if state is None:
        return
    # Flatten metrics into stable namespaces so W&B plots line up across click
    # and keyboard experiments.
    payload: dict[str, Any] = {"epoch": epoch, "score/loss": score}
    payload.update(score_metrics)
    payload.update({f"train/{key}": value for key, value in train_metrics.items()})
    payload.update({f"val/{key}": value for key, value in val_metrics.items()})
    if math.isfinite(best_score):
        payload["best/loss"] = best_score
        payload["best/epoch"] = best_epoch
    if best_composite_score is not None and math.isfinite(best_composite_score):
        payload["best/composite"] = best_composite_score
    if lr is not None:
        payload["optimizer/lr"] = lr
    state.run.log(payload, step=epoch)


def wandb_log_artifacts(state: WandbState | None, task: str, run_dir: Path) -> None:
    """Upload checkpoints and metrics from a training run directory to W&B."""
    if state is None:
        return
    artifact_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{task}-{run_dir.name}-checkpoints")
    artifact = state.module.Artifact(artifact_name, type="model")
    # Upload only files that were actually produced; short failed runs may not
    # have all checkpoint variants.
    for filename in ("model-best.pt", "model.pt", "metrics.jsonl"):
        path = run_dir / filename
        if path.exists():
            artifact.add_file(str(path), name=filename)
    state.run.log_artifact(artifact)
