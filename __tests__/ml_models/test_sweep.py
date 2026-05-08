from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rotunda_models.random_sweep import (
    parameter_aliases_for,
    prepare_trial_settings,
    resolve_base_settings,
    run_sweep,
)
from rotunda_models.settings import load_sweep_settings


def write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def base_training_config(*, task: str = "keyboard", inputs: list[str] | None = None) -> dict:
    return {
        "name": "test-root",
        "task": task,
        "data": {
            "inputs": inputs or ["recordings"],
        },
        "training": {
            "epochs": 25,
            "batch_size": 16,
            "hidden_size": 128,
            "layers": 1,
            "dropout": 0.0,
            "lr": 0.001,
            "weight_decay": 0.0001,
            "val_fraction": 0.15,
            "seed": 13,
            "early_stopping_patience": 0,
            "early_stopping_min_delta": 0.0,
        },
        "keyboard": {
            "keyboard_typo_positive_weight": 4.0,
        },
        "clicks": {
            "min_distance": 8.0,
        },
        "wandb": {
            "enabled": True,
            "project": "cadence-models",
        },
    }


def test_load_sweep_settings_resolves_root_config_relative_to_spec(tmp_path: Path) -> None:
    root_config = write_yaml(tmp_path / "configs" / "root.yml", base_training_config())
    sweep_config = write_yaml(
        tmp_path / "sweeps" / "keyboard.yml",
        {
            "root_config": "../configs/root.yml",
            "parameters": {
                "training.lr": {"values": [0.001, 0.002]},
            },
        },
    )

    settings = load_sweep_settings(sweep_config)

    assert settings.root_config == root_config.resolve()
    assert settings.parameters["training.lr"]["values"] == [0.001, 0.002]


def test_resolve_base_settings_allows_task_override_from_all(tmp_path: Path) -> None:
    root_config = write_yaml(tmp_path / "root.yml", base_training_config(task="all"))

    settings = resolve_base_settings(
        root_config,
        {
            "task": "keyboard",
            "keyboard.keyboard_typo_positive_weight": 12.0,
        },
    )

    assert settings.task == "keyboard"
    assert settings.keyboard.keyboard_typo_positive_weight == 12.0


def test_parameter_aliases_reject_paths_for_inactive_task(tmp_path: Path) -> None:
    root_config = write_yaml(tmp_path / "root.yml", base_training_config(task="keyboard"))
    settings = resolve_base_settings(root_config, {})

    with pytest.raises(SystemExit, match="does not apply to task 'keyboard'"):
        parameter_aliases_for(
            settings,
            {},
            {
                "clicks.min_distance": {"values": [8.0, 12.0]},
            },
        )


def test_prepare_trial_settings_applies_sampled_and_runtime_overrides(tmp_path: Path) -> None:
    root_config = write_yaml(tmp_path / "root.yml", base_training_config(task="keyboard"))
    settings = resolve_base_settings(root_config, {})

    trial = prepare_trial_settings(
        base_settings=settings,
        sampled_overrides={
            "training.lr": 0.002,
            "keyboard.keyboard_typo_positive_weight": 12.0,
        },
        training_inputs=[str(tmp_path / "snapshot")],
        run_output_dir=tmp_path / "runs" / "trial-1",
        group="keyboard-sweep",
    )

    assert trial.training.lr == 0.002
    assert trial.keyboard.keyboard_typo_positive_weight == 12.0
    assert trial.data.inputs == [str(tmp_path / "snapshot")]
    assert trial.training.output_dir == tmp_path / "runs" / "trial-1"
    assert trial.wandb.enabled is True
    assert trial.wandb.mode == "online"
    assert trial.wandb.group == "keyboard-sweep"
    assert trial.wandb.run_name is None


def test_run_sweep_dry_run_writes_yaml_defined_sweep_config(tmp_path: Path) -> None:
    recordings = tmp_path / "captures"
    recordings.mkdir()
    root_config = write_yaml(
        tmp_path / "configs" / "root.yml",
        base_training_config(inputs=["../captures"]),
    )
    sweep_config = write_yaml(
        tmp_path / "sweeps" / "keyboard.yml",
        {
            "root_config": "../configs/root.yml",
            "output_dir": str(tmp_path / "sweep-output"),
            "overrides": {
                "training.epochs": 20,
            },
            "parameters": {
                "training.lr": {
                    "type": "loguniform",
                    "min": 0.0003,
                    "max": 0.003,
                },
                "keyboard.keyboard_typo_positive_weight": {
                    "values": [4.0, 8.0, 12.0],
                },
            },
        },
    )

    code = run_sweep(SimpleNamespace(config=sweep_config, dry_run=True, create_only=False))

    assert code == 0
    sweep_dirs = list((tmp_path / "sweep-output").glob("wandb-sweep-*"))
    assert len(sweep_dirs) == 1

    sweep_json = json.loads((sweep_dirs[0] / "sweep.json").read_text(encoding="utf-8"))
    meta_json = json.loads((sweep_dirs[0] / "meta.json").read_text(encoding="utf-8"))

    assert sweep_json["parameters"]["training__lr"]["distribution"] == "log_uniform_values"
    assert sweep_json["parameters"]["keyboard__keyboard_typo_positive_weight"]["values"] == [4.0, 8.0, 12.0]
    assert meta_json["root_config"] == str(root_config.resolve())
    assert meta_json["inputs"] == [str(recordings.resolve())]
