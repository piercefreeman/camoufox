"""BaseSettings-backed training experiment configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .types import ScreenSizeFilter


class DataSettings(BaseModel):
    inputs: list[str] = Field(default_factory=lambda: ["recordings"])
    screen_filter: ScreenSizeFilter = Field(default_factory=ScreenSizeFilter)

    @field_validator("inputs", mode="before")
    @classmethod
    def normalize_inputs(cls, value):
        if value is None:
            return ["recordings"]
        if isinstance(value, str):
            return [value]
        return value


class TrainingSettings(BaseModel):
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
    gap_ms: int = 1000
    synthetic_per_sequence: int = 4
    geometry_tolerance: float = 0.05
    include_repeats: bool = False
    keyboard_text_source: Literal["auto", "focused", "synthetic"] = "auto"
    keyboard_accessibility_id: str | None = "auto"
    keyboard_max_snapshot_edit_actions: int = 12
    keyboard_sequence_mode: Literal["auto", "constrained", "raw"] = "auto"
    keyboard_min_final_length: int = 1
    keyboard_min_duration_ms: float = 0.0
    char_embed_size: int = 32
    action_embed_size: int = 32
    dt_loss_weight: float = 1.0
    keyboard_action_loss_weight: float = 1.0
    keyboard_duration_loss_weight: float = 1.0
    backspace_action_weight: float = 4.0
    stop_action_weight: float = 8.0
    wandb_keyboard_rollout_examples: int = 128
    wandb_keyboard_rollout_max_steps: int = 256


class TrainingExperimentSettings(BaseSettings):
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
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must contain a YAML object.")
        settings = cls(**raw)
        config_dir = path.resolve().parent
        settings.data.inputs = [
            str((config_dir / item).resolve()) if not Path(item).is_absolute() else item
            for item in settings.data.inputs
        ]
        settings.training.output_dir = Path(settings.training.output_dir)
        return settings

    def to_namespace(self, task: Literal["clicks", "keyboard"]) -> argparse.Namespace:
        if self.task != "all" and self.task != task:
            raise ValueError(f"Experiment task is {self.task!r}, not {task!r}.")

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
        return argparse.Namespace(**values)


def load_experiment_settings(path: Path) -> TrainingExperimentSettings:
    return TrainingExperimentSettings.from_yaml(path)
