#!/usr/bin/env python3
"""Create and run W&B sweeps from YAML-defined cadence experiments."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click

from . import train as training
from .cli.common import CONTEXT_SETTINGS, PATH_TYPE
from .settings import (
    TrainingExperimentSettings,
    apply_settings_overrides,
    load_sweep_settings,
)
from .utils import log_labeled
from .wandb import import_wandb, parse_wandb_tags

RESERVED_SWEEP_PATHS = {"task", "data.inputs", "training.output_dir"}
RESERVED_SWEEP_PREFIXES = ("wandb.",)
COMMON_SWEEP_SECTIONS = {"name", "task", "data", "training", "wandb"}


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


def to_wandb_parameter(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {"value": spec}
    if "value" in spec:
        return {"value": spec["value"]}
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


def parameter_alias(path: str) -> str:
    """Map a dotted config path to a stable W&B sweep parameter key."""
    return path.replace(".", "__")


def sweep_name(base_name: str | None, task: str, stamp: str) -> str:
    if base_name:
        return base_name
    return f"cadence-{task}-{stamp}"


def _value_at_path(target: dict[str, Any], dotted_path: str) -> Any:
    current: Any = target
    parts = dotted_path.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError(f"Invalid sweep path: {dotted_path!r}")
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Unknown sweep path: {dotted_path!r}")
        current = current[part]
    return current


def validate_override_paths(
    settings: TrainingExperimentSettings,
    overrides: dict[str, Any],
    *,
    allow_reserved: bool,
    enforce_task_sections: bool,
) -> None:
    """Fail fast when dotted sweep paths do not map to the active config."""
    raw = settings.model_dump(mode="python")
    allowed_sections = COMMON_SWEEP_SECTIONS | {settings.task}
    for dotted_path in sorted(overrides):
        top_level = dotted_path.split(".", 1)[0]
        if enforce_task_sections and top_level not in allowed_sections:
            raise SystemExit(
                f"Sweep path {dotted_path!r} does not apply to task {settings.task!r}. "
                f"Allowed sections: {', '.join(sorted(allowed_sections))}."
            )
        _value_at_path(raw, dotted_path)
        if allow_reserved:
            continue
        if dotted_path in RESERVED_SWEEP_PATHS or dotted_path.startswith(RESERVED_SWEEP_PREFIXES):
            raise SystemExit(
                f"Sweep parameter path {dotted_path!r} is reserved for sweep orchestration. "
                "Put fixed run-level changes under 'overrides' instead."
            )


def parameter_aliases_for(
    settings: TrainingExperimentSettings,
    overrides: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, str]:
    """Validate parameter paths and return W&B alias-to-config-path mapping."""
    if not parameters:
        raise SystemExit("Sweep config must define at least one sampled entry under 'parameters'.")
    validate_override_paths(
        settings,
        parameters,
        allow_reserved=False,
        enforce_task_sections=True,
    )

    aliases: dict[str, str] = {}
    for dotted_path in sorted(parameters):
        if dotted_path in overrides:
            raise SystemExit(
                f"Sweep path {dotted_path!r} is defined in both 'overrides' and 'parameters'."
            )
        alias = parameter_alias(dotted_path)
        other = aliases.get(alias)
        if other is not None and other != dotted_path:
            raise SystemExit(
                f"Sweep parameter alias collision: {dotted_path!r} and {other!r} both map to {alias!r}."
            )
        aliases[alias] = dotted_path
    return aliases


def sweep_config_for(
    name: str,
    parameters: dict[str, Any],
    aliases: dict[str, str],
    method: str,
    metric_name: str,
    metric_goal: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "method": method,
        "metric": {"name": metric_name, "goal": metric_goal},
        "parameters": {
            alias: to_wandb_parameter(parameters[path])
            for alias, path in sorted(aliases.items())
        },
    }


def selected_sweep_params(
    aliases: dict[str, str],
    wandb_config: Any,
) -> dict[str, Any]:
    config = dict(wandb_config)
    return {
        dotted_path: config[alias]
        for alias, dotted_path in sorted(aliases.items())
        if alias in config
    }


def prepare_trial_settings(
    base_settings: TrainingExperimentSettings,
    sampled_overrides: dict[str, Any],
    training_inputs: list[str],
    run_output_dir: Path,
    group: str,
) -> TrainingExperimentSettings:
    """Resolve one sampled trial into a concrete training experiment config."""
    settings = apply_settings_overrides(base_settings, sampled_overrides)
    runtime_overrides: dict[str, Any] = {
        "data.inputs": training_inputs,
        "training.output_dir": run_output_dir,
        "wandb.enabled": True,
        "wandb.mode": "online",
        "wandb.run_name": None,
    }
    if settings.wandb.group is None:
        runtime_overrides["wandb.group"] = group
    return apply_settings_overrides(settings, runtime_overrides)


def run_training_trial(
    base_settings: TrainingExperimentSettings,
    parameter_aliases: dict[str, str],
    sweep_dir: Path,
    training_inputs: list[str],
    root_config: Path,
    fixed_overrides: dict[str, Any],
    group: str,
) -> None:
    wandb = import_wandb()
    run = wandb.init(
        project=base_settings.wandb.project,
        entity=base_settings.wandb.entity,
        group=base_settings.wandb.group or group,
        tags=parse_wandb_tags(base_settings.wandb.tags) or None,
        mode="online",
        config={
            "task": base_settings.task,
            "root_config": str(root_config),
            "fixed_overrides": fixed_overrides,
            "sampled_parameter_aliases": parameter_aliases,
            "training_inputs": training_inputs,
            "local_sweep_dir": str(sweep_dir),
        },
    )
    try:
        sampled_overrides = selected_sweep_params(parameter_aliases, wandb.config)
        run_output_dir = sweep_dir / base_settings.task / "runs" / str(run.id)
        trial_settings = prepare_trial_settings(
            base_settings=base_settings,
            sampled_overrides=sampled_overrides,
            training_inputs=training_inputs,
            run_output_dir=run_output_dir,
            group=group,
        )
        log(
            "[sweep] "
            f"task={trial_settings.task} wandb_run={run.name} "
            f"overrides={json.dumps(sampled_overrides, sort_keys=True)}"
        )
        if trial_settings.task == "clicks":
            training.train_clicks(trial_settings)
        else:
            training.train_keyboard(trial_settings)
    finally:
        wandb.finish()


def resolve_base_settings(config_path: Path, fixed_overrides: dict[str, Any]) -> TrainingExperimentSettings:
    """Load the root config, apply fixed overrides, and enforce a single task."""
    root_settings = TrainingExperimentSettings.from_yaml(config_path)
    if fixed_overrides:
        validate_override_paths(
            root_settings,
            fixed_overrides,
            allow_reserved=True,
            enforce_task_sections=False,
        )
        root_settings = apply_settings_overrides(root_settings, fixed_overrides)
    if root_settings.task not in {"clicks", "keyboard"}:
        raise SystemExit(
            "Sweep root config must resolve to a single task. "
            "Set task to 'clicks' or 'keyboard' in the root config or under 'overrides'."
        )
    validate_override_paths(
        root_settings,
        fixed_overrides,
        allow_reserved=True,
        enforce_task_sections=True,
    )
    if not root_settings.wandb.project:
        raise SystemExit(
            "Sweep root config must define wandb.project. "
            "Set it in the root config or under sweep 'overrides'."
        )
    return root_settings


def run_sweep(args: Any) -> int:
    """Create a W&B sweep from a YAML sweep spec and optionally launch an agent."""
    sweep_settings = load_sweep_settings(args.config)
    base_settings = resolve_base_settings(sweep_settings.root_config, sweep_settings.overrides)
    aliases = parameter_aliases_for(base_settings, sweep_settings.overrides, sweep_settings.parameters)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    sweep_dir = sweep_settings.output_dir / f"wandb-sweep-{stamp}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    raw_inputs = list(base_settings.data.inputs)
    training_inputs = raw_inputs
    if sweep_settings.snapshot_inputs and not args.dry_run:
        # Sweeps should train against immutable inputs so long-running agents do
        # not observe different corpora if recordings continue to be added.
        training_inputs = snapshot_inputs(raw_inputs, sweep_dir)
    log(f"[sweep] local_dir={sweep_dir}")

    name = sweep_name(sweep_settings.name, base_settings.task, stamp)
    config = sweep_config_for(
        name=name,
        parameters=sweep_settings.parameters,
        aliases=aliases,
        method=sweep_settings.method,
        metric_name=sweep_settings.metric.name,
        metric_goal=sweep_settings.metric.goal,
    )
    write_json(sweep_dir / "sweep.json", config)
    log(f"[sweep] config={sweep_dir / 'sweep.json'}")

    write_json(
        sweep_dir / "meta.json",
        {
            "task": base_settings.task,
            "trials": sweep_settings.trials,
            "method": sweep_settings.method,
            "metric": sweep_settings.metric.model_dump(),
            "root_config": str(sweep_settings.root_config),
            "root_config_name": base_settings.name,
            "wandb_project": base_settings.wandb.project,
            "wandb_entity": base_settings.wandb.entity,
            "inputs": raw_inputs,
            "training_inputs": training_inputs,
            "snapshot_inputs": sweep_settings.snapshot_inputs and not args.dry_run,
            "overrides": sweep_settings.overrides,
            "parameters": sweep_settings.parameters,
            "parameter_aliases": aliases,
        },
    )

    if args.dry_run:
        print(json.dumps(config, indent=2, sort_keys=True))
        return 0

    wandb = import_wandb()
    sweep_id = wandb.sweep(
        config,
        project=base_settings.wandb.project,
        entity=base_settings.wandb.entity,
    )
    log(f"[sweep] task={base_settings.task} wandb_sweep_id={sweep_id}")
    if args.create_only or sweep_settings.trials <= 0:
        return 0

    def train_one() -> None:
        # W&B agents call a zero-argument function, so bind the sweep context
        # before handing control to the SDK.
        run_training_trial(
            base_settings=base_settings,
            parameter_aliases=aliases,
            sweep_dir=sweep_dir,
            training_inputs=training_inputs,
            root_config=sweep_settings.root_config,
            fixed_overrides=sweep_settings.overrides,
            group=name,
        )

    wandb.agent(
        sweep_id,
        function=train_one,
        count=sweep_settings.trials,
        project=base_settings.wandb.project,
        entity=base_settings.wandb.entity,
    )
    return 0


@click.command(context_settings=CONTEXT_SETTINGS, help=__doc__)
@click.argument("config", type=PATH_TYPE)
@click.option("--create-only", is_flag=True, default=False, help="Create the W&B sweep and do not launch an agent.")
@click.option("--dry-run", is_flag=True, default=False, help="Write/print the generated sweep config without contacting W&B.")
def sweep_command(config: Path, create_only: bool, dry_run: bool) -> None:
    """Create a W&B sweep from a YAML sweep spec and optionally launch an agent."""
    code = run_sweep(SimpleNamespace(config=config, create_only=create_only, dry_run=dry_run))
    if code:
        raise click.exceptions.Exit(code)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the sweep command."""
    try:
        sweep_command.main(args=argv, prog_name="rotunda-models-sweep", standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
