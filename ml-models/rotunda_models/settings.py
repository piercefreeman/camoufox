"""BaseSettings-backed training experiment configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .types import ScreenSizeFilter


class DataSettings(BaseModel):
    """Recording inputs and event-level corpus filters for an experiment."""

    inputs: list[str] = Field(default_factory=lambda: ["recordings"])
    screen_filter: ScreenSizeFilter = Field(default_factory=ScreenSizeFilter)

    @field_validator("inputs", mode="before")
    @classmethod
    def normalize_inputs(cls, value):
        """Accept one input path or a list of input paths from YAML/env."""
        if value is None:
            return ["recordings"]
        if isinstance(value, str):
            return [value]
        return value


class TrainingSettings(BaseModel):
    """Model-agnostic optimization and run-output settings."""

    output_dir: Path = Path("Training/runs")
    epochs: int = 25
    batch_size: int = 32
    hidden_size: int = 96
    layers: int = 1
    dropout: float = 0.0
    lr: float = 1e-3
    weight_decay: float = 1e-4
    val_fraction: float = 0.15
    seed: int = 13
    device: str | None = None
    early_stopping_patience: int = 0
    early_stopping_min_delta: float = 0.0


class WandbSettings(BaseModel):
    """Optional W&B tracking settings mirrored onto the training namespace."""

    enabled: bool = False
    project: str | None = None
    entity: str | None = None
    run_name: str | None = None
    group: str | None = None
    tags: str = ""
    mode: Literal["online", "offline", "disabled"] | None = None
    watch: bool = False
    log_artifacts: bool = True

    def to_namespace_fields(self) -> dict[str, object]:
        """Return flat namespace keys expected by the training/wandb helpers."""
        return {
            "wandb": self.enabled,
            "wandb_project": self.project,
            "wandb_entity": self.entity,
            "wandb_run_name": self.run_name,
            "wandb_group": self.group,
            "wandb_tags": self.tags,
            "wandb_mode": self.mode,
            "wandb_watch": self.watch,
            "wandb_log_artifacts": self.log_artifacts,
        }


class ClickSettings(BaseModel):
    """Mouse click extraction, loss weighting, and rollout settings."""

    rest_ms: int = 150
    max_duration_ms: int = 2000
    min_distance: float = 8.0
    dt_loss_weight: float = 1.0
    pos_loss_weight: float = 1.0
    click_action_weight: float = 8.0
    click_duration_loss_weight: float = 0.0
    wandb_click_rollout_examples: int = 128
    wandb_click_rollout_max_steps: int = 80
    wandb_click_rollout_click_threshold: float = 0.98
    wandb_click_rollout_min_dt_ms: float = 4.0


class KeyboardSettings(BaseModel):
    """Keyboard extraction, decoding, architecture, and loss settings."""

    gap_ms: int = 1000
    keyboard_accessibility_id: str | None = "auto"
    keyboard_min_final_length: int = 1
    keyboard_min_duration_ms: float = 0.0
    keyboard_max_condition_length: int | None = 1024
    keyboard_max_steps: int | None = 256
    char_embed_size: int = 32
    action_embed_size: int = 32
    dt_loss_weight: float = 1.0
    keyboard_action_loss_weight: float = 1.0
    keyboard_duration_loss_weight: float = 1.0
    keyboard_press_count_loss_weight: float = 1.0
    keyboard_typo_loss_weight: float = 1.0
    keyboard_typo_action_loss_weight: float = 1.0
    keyboard_typo_positive_weight: float = 8.0
    backspace_action_weight: float = 4.0
    stop_action_weight: float = 8.0
    wandb_keyboard_rollout_examples: int = 128
    wandb_keyboard_rollout_max_steps: int = 256
    wandb_keyboard_inspect_examples: int = 100

    @field_validator("keyboard_max_condition_length", "keyboard_max_steps")
    @classmethod
    def normalize_optional_positive_int(cls, value: int | None) -> int | None:
        """Treat non-positive length caps as disabled."""
        if value is not None and value <= 0:
            return None
        return value


class TrainingExperimentSettings(BaseSettings):
    """Top-level YAML/env settings object for a training experiment."""

    model_config = SettingsConfigDict(
        env_prefix="ROTUNDA_MODELS_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    name: str | None = None
    task: Literal["all", "clicks", "keyboard"] = "all"
    data: DataSettings = Field(default_factory=DataSettings)
    training: TrainingSettings = Field(default_factory=TrainingSettings)
    wandb: WandbSettings = Field(default_factory=WandbSettings)
    clicks: ClickSettings = Field(default_factory=ClickSettings)
    keyboard: KeyboardSettings = Field(default_factory=KeyboardSettings)

    @classmethod
    def from_yaml(cls, path: Path) -> TrainingExperimentSettings:
        """Load an experiment YAML file and resolve relative input paths."""
        raw = load_yaml_mapping(path)
        settings = cls(**raw)
        # Treat recording inputs as relative to the YAML file so config/*.yml can
        # be moved or run from different current working directories.
        config_dir = path.resolve().parent
        settings.data.inputs = [
            str((config_dir / item).resolve()) if not Path(item).is_absolute() else item
            for item in settings.data.inputs
        ]
        settings.training.output_dir = Path(settings.training.output_dir)
        return settings

    def to_namespace(self, task: Literal["clicks", "keyboard"]) -> SimpleNamespace:
        """Flatten settings into the namespace shape consumed by train_clicks/keyboard."""
        if self.task != "all" and self.task != task:
            raise ValueError(f"Experiment task is {self.task!r}, not {task!r}.")

        # Keep the training functions stable during the CLI-to-settings migration
        # by projecting nested settings onto their historical flat keys.
        values: dict[str, object] = {
            "task": task,
            "experiment_name": self.name,
            "inputs": list(self.data.inputs),
            "screen_filter": self.data.screen_filter,
        }
        values.update(self.training.model_dump())
        values.update(self.wandb.to_namespace_fields())
        if task == "clicks":
            values.update(self.clicks.model_dump())
        else:
            values.update(self.keyboard.model_dump())
        values["output_dir"] = Path(values["output_dir"])
        return SimpleNamespace(**values)


def load_experiment_settings(path: Path) -> TrainingExperimentSettings:
    """Load a YAML-backed training experiment settings object."""
    return TrainingExperimentSettings.from_yaml(path)


class SweepMetricSettings(BaseModel):
    """Metric selection for a W&B sweep."""

    name: str = "score/loss"
    goal: Literal["minimize", "maximize"] = "minimize"


class SweepExperimentSettings(BaseModel):
    """YAML-backed W&B sweep definition rooted in a training config."""

    root_config: Path
    name: str | None = None
    method: Literal["random", "bayes", "grid"] = "random"
    trials: int = 8
    output_dir: Path = Path("Training/sweeps")
    snapshot_inputs: bool = True
    metric: SweepMetricSettings = Field(default_factory=SweepMetricSettings)
    overrides: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> SweepExperimentSettings:
        """Load a sweep YAML file and resolve the linked root config path."""
        raw = load_yaml_mapping(path)
        settings = cls(**raw)
        if not settings.root_config.is_absolute():
            settings.root_config = (path.resolve().parent / settings.root_config).resolve()
        settings.output_dir = Path(settings.output_dir)
        return settings


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file that must contain a mapping object."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML object.")
    return raw


def _set_dotted_value(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a nested mapping value and fail on unknown paths."""
    parts = dotted_path.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError(f"Invalid override path: {dotted_path!r}")

    current: Any = target
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Unknown override path: {dotted_path!r}")
        current = current[part]
    leaf = parts[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise ValueError(f"Unknown override path: {dotted_path!r}")
    current[leaf] = value


def apply_settings_overrides(
    settings: TrainingExperimentSettings,
    overrides: Mapping[str, Any],
) -> TrainingExperimentSettings:
    """Apply dotted-path overrides and revalidate the training settings."""
    if not overrides:
        return settings
    raw = settings.model_dump(mode="python")
    for dotted_path, value in overrides.items():
        _set_dotted_value(raw, dotted_path, value)
    updated = TrainingExperimentSettings.model_validate(raw)
    updated.training.output_dir = Path(updated.training.output_dir)
    return updated


def load_sweep_settings(path: Path) -> SweepExperimentSettings:
    """Load a YAML-backed sweep definition."""
    return SweepExperimentSettings.from_yaml(path)
