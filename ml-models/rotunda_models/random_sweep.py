#!/usr/bin/env python3
"""Create and run Weights & Biases sweeps for cadence models."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from . import train as training
from .cli.main import build_parser as build_training_parser
from .utils import log_labeled

DEFAULT_SPACES: dict[str, dict[str, Any]] = {
    "clicks": {
        "batch_size": {"values": [16, 32, 64]},
        "hidden_size": {"values": [64, 96, 128, 192]},
        "layers": {"values": [1, 2]},
        "dropout": {"values": [0.0, 0.05, 0.1, 0.2]},
        "lr": {"type": "loguniform", "min": 3e-4, "max": 3e-3},
        "weight_decay": {"type": "loguniform", "min": 1e-6, "max": 1e-3},
        "dt_loss_weight": {"type": "loguniform", "min": 0.5, "max": 8.0},
        "pos_loss_weight": {"type": "loguniform", "min": 0.5, "max": 4.0},
        "click_duration_loss_weight": {"type": "loguniform", "min": 0.5, "max": 8.0},
        "click_action_weight": {"type": "uniform", "min": 4.0, "max": 18.0},
        "rest_ms": {"values": [100, 150, 200, 250]},
        "min_distance": {"values": [6.0, 8.0, 12.0, 18.0]},
    },
    "keyboard": {
        "batch_size": {"values": [32, 64, 96]},
        "hidden_size": {"values": [64, 96, 128, 192]},
        "layers": {"values": [1, 2]},
        "dropout": {"values": [0.0, 0.05, 0.1, 0.2]},
        "lr": {"type": "loguniform", "min": 3e-4, "max": 3e-3},
        "weight_decay": {"type": "loguniform", "min": 1e-6, "max": 1e-3},
        "dt_loss_weight": {"type": "loguniform", "min": 1.0, "max": 16.0},
        "keyboard_action_loss_weight": {"values": [0.1, 0.3, 1.0]},
        "keyboard_duration_loss_weight": {"type": "loguniform", "min": 0.5, "max": 8.0},
        "backspace_action_weight": {"type": "uniform", "min": 2.0, "max": 10.0},
        "stop_action_weight": {"type": "uniform", "min": 4.0, "max": 18.0},
        "gap_ms": {"values": [500, 750, 1000, 1500]},
        "synthetic_per_sequence": {"values": [4, 8, 12, 16, 24]},
        "geometry_tolerance": {"values": [0.05, 0.08, 0.1]},
        "char_embed_size": {"values": [16, 32, 48]},
        "action_embed_size": {"values": [16, 32, 48]},
    },
}


def log(message: str) -> None:
    log_labeled("sweep", message.removeprefix("[sweep] ").strip(), "magenta")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)


def snapshot_inputs(inputs: list[str], sweep_dir: Path) -> list[str]:
    snapshot_root = sweep_dir / "input_snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    copied = 0

    for input_index, item in enumerate(inputs):
        source = Path(item)
        if source.is_file() and source.suffix.lower() in {".ndjson", ".jsonl"}:
            destination = snapshot_root / "files" / f"{input_index:02d}-{source.name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest.append({"source": str(source), "snapshot": str(destination)})
            copied += 1
        elif source.is_dir():
            for path in sorted(list(source.rglob("*.ndjson")) + list(source.rglob("*.jsonl"))):
                relative = path.relative_to(source)
                destination = snapshot_root / source.name / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                manifest.append({"source": str(path), "snapshot": str(destination)})
                copied += 1

    with (snapshot_root / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    if copied == 0:
        raise SystemExit("No .ndjson or .jsonl inputs found to snapshot.")
    log(f"[sweep] snapshotted {copied} input file(s) to {snapshot_root}")
    return [str(snapshot_root)]


def load_space(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return DEFAULT_SPACES
    with path.open("r", encoding="utf-8") as handle:
        override = json.load(handle)
    space = json.loads(json.dumps(DEFAULT_SPACES))
    for task, task_space in override.items():
        if task not in space:
            space[task] = {}
        space[task].update(task_space)
    return space


def to_wandb_parameter(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {"value": spec}
    if "values" in spec:
        return {"values": spec["values"]}

    spec_type = spec.get("type", "uniform")
    if spec_type == "uniform":
        return {"distribution": "uniform", "min": float(spec["min"]), "max": float(spec["max"])}
    if spec_type == "loguniform":
        return {"distribution": "log_uniform_values", "min": float(spec["min"]), "max": float(spec["max"])}
    if spec_type == "int":
        return {"distribution": "int_uniform", "min": int(spec["min"]), "max": int(spec["max"])}
    raise ValueError(f"Unknown sweep spec type: {spec_type!r}")


def sweep_name(base_name: str | None, task: str, stamp: str, multiple_tasks: bool) -> str:
    if base_name and multiple_tasks:
        return f"{base_name}-{task}"
    if base_name:
        return base_name
    return f"cadence-{task}-{stamp}"


def sweep_config_for(
    task: str,
    name: str,
    space: dict[str, Any],
    method: str,
    metric_name: str,
    metric_goal: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "method": method,
        "metric": {"name": metric_name, "goal": metric_goal},
        "parameters": {key: to_wandb_parameter(value) for key, value in sorted(space.items())},
    }


def coerce_value(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def make_training_args(
    task: str,
    sweep_args: argparse.Namespace,
    inputs: list[str],
    params: dict[str, Any],
    run_output_dir: Path,
    group: str,
) -> argparse.Namespace:
    subcommand = "train-clicks" if task == "clicks" else "train-keyboard"
    args = build_training_parser().parse_args([subcommand])
    args.inputs = inputs
    args.output_dir = run_output_dir
    args.epochs = sweep_args.epochs
    args.early_stopping_patience = sweep_args.early_stopping_patience
    args.early_stopping_min_delta = sweep_args.early_stopping_min_delta
    args.seed = sweep_args.seed
    args.device = sweep_args.device
    args.wandb = True
    args.wandb_project = sweep_args.wandb_project
    args.wandb_entity = sweep_args.wandb_entity
    args.wandb_run_name = None
    args.wandb_group = sweep_args.wandb_group or group
    args.wandb_tags = sweep_args.wandb_tags
    args.wandb_mode = sweep_args.wandb_mode
    args.wandb_watch = sweep_args.wandb_watch
    args.wandb_log_artifacts = sweep_args.wandb_log_artifacts

    for name, value in sorted(params.items()):
        default = getattr(args, name, None)
        setattr(args, name, coerce_value(value, default))
    return args


def selected_sweep_params(task: str, space: dict[str, Any], wandb_config: Any) -> dict[str, Any]:
    config = dict(wandb_config)
    return {name: config[name] for name in sorted(space) if name in config}


def run_training_trial(
    task: str,
    space: dict[str, Any],
    sweep_args: argparse.Namespace,
    training_inputs: list[str],
    sweep_dir: Path,
    group: str,
) -> None:
    wandb = training.import_wandb()
    run = wandb.init(
        project=sweep_args.wandb_project,
        entity=sweep_args.wandb_entity,
        group=sweep_args.wandb_group or group,
        tags=training.parse_wandb_tags(sweep_args.wandb_tags) or None,
        mode=sweep_args.wandb_mode,
        config={
            "task": task,
            "epochs": sweep_args.epochs,
            "training_inputs": training_inputs,
            "snapshot_inputs": sweep_args.snapshot_inputs,
            "local_sweep_dir": str(sweep_dir),
        },
    )
    try:
        params = selected_sweep_params(task, space, wandb.config)
        run_output_dir = sweep_dir / task / "runs" / str(run.id)
        train_args = make_training_args(
            task=task,
            sweep_args=sweep_args,
            inputs=training_inputs,
            params=params,
            run_output_dir=run_output_dir,
            group=group,
        )
        log(f"[sweep] task={task} wandb_run={run.name} params={json.dumps(params, sort_keys=True)}")
        if task == "clicks":
            training.train_clicks(train_args)
        else:
            training.train_keyboard(train_args)
    finally:
        wandb.finish()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", default=["recordings"], help="Recording files or directories.")
    parser.add_argument("--task", choices=["all", "clicks", "keyboard"], default="all")
    parser.add_argument("--trials", type=int, default=8, help="W&B agent runs per selected task.")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--early-stopping-patience", type=int, default=5)
    parser.add_argument("--early-stopping-min-delta", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--device", default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("Training/sweeps"))
    parser.add_argument("--space", type=Path, default=None, help="Optional JSON file overriding default search spaces.")
    parser.add_argument("--snapshot-inputs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--wandb-project", default="cadence-models")
    parser.add_argument("--wandb-entity", default=None)
    parser.add_argument("--wandb-group", default=None)
    parser.add_argument("--wandb-tags", default="", help="Comma-separated W&B tags for all runs.")
    parser.add_argument("--wandb-mode", choices=["online"], default="online", help="W&B sweeps require online mode.")
    parser.add_argument("--wandb-watch", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--wandb-log-artifacts", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--method", choices=["random", "bayes", "grid"], default="random")
    parser.add_argument("--metric-name", default="score/loss")
    parser.add_argument("--metric-goal", choices=["minimize", "maximize"], default="minimize")
    parser.add_argument("--sweep-name", default=None)
    parser.add_argument("--create-only", action="store_true", help="Create the W&B sweep and do not launch an agent.")
    parser.add_argument("--dry-run", action="store_true", help="Write/print sweep configs without contacting W&B.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spaces = load_space(args.space)
    selected_tasks = ["clicks", "keyboard"] if args.task == "all" else [args.task]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sweep_dir = args.output_dir / f"wandb-sweep-{stamp}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    training_inputs = args.inputs
    if args.snapshot_inputs and not args.dry_run:
        training_inputs = snapshot_inputs(args.inputs, sweep_dir)
    log(f"[sweep] local_dir={sweep_dir}")

    configs: dict[str, dict[str, Any]] = {}
    for task in selected_tasks:
        name = sweep_name(args.sweep_name, task, stamp, multiple_tasks=len(selected_tasks) > 1)
        config = sweep_config_for(
            task=task,
            name=name,
            space=spaces[task],
            method=args.method,
            metric_name=args.metric_name,
            metric_goal=args.metric_goal,
        )
        configs[task] = config
        write_json(sweep_dir / f"{task}-sweep.json", config)
        log(f"[sweep] config={sweep_dir / f'{task}-sweep.json'}")

    write_json(
        sweep_dir / "meta.json",
        {
            "tasks": selected_tasks,
            "trials_per_task": args.trials,
            "epochs": args.epochs,
            "inputs": args.inputs,
            "training_inputs": training_inputs,
            "snapshot_inputs": args.snapshot_inputs and not args.dry_run,
            "wandb_project": args.wandb_project,
            "wandb_entity": args.wandb_entity,
        },
    )

    if args.dry_run:
        print(json.dumps(configs, indent=2, sort_keys=True))
        return 0

    wandb = training.import_wandb()
    for task in selected_tasks:
        group = sweep_name(args.sweep_name, task, stamp, multiple_tasks=len(selected_tasks) > 1)
        sweep_id = wandb.sweep(configs[task], project=args.wandb_project, entity=args.wandb_entity)
        log(f"[sweep] task={task} wandb_sweep_id={sweep_id}")
        if args.create_only or args.trials <= 0:
            continue

        def train_one(
            task: str = task,
            space: dict[str, Any] = spaces[task],
            group: str = group,
        ) -> None:
            run_training_trial(
                task=task,
                space=space,
                sweep_args=args,
                training_inputs=training_inputs,
                sweep_dir=sweep_dir,
                group=group,
            )

        wandb.agent(
            sweep_id,
            function=train_one,
            count=args.trials,
            project=args.wandb_project,
            entity=args.wandb_entity,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
