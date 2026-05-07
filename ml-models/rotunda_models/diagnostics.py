"""Rollout diagnostics written locally and optionally logged to W&B."""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import torch

from .constants import MOUSE_ACTIONS
from .generation import decode_keyboard_rows, simulate_mouse_click_rows
from .keyboard_logic import canonical_keyboard_steps, terminal_edit_actions
from .models.keyboard import KeyboardActionGRU
from .models.mouse import MouseTrajectoryGRU
from .training_utils import keyboard_episode_duration_ms
from .types import KeyboardEpisode, MouseEpisode, WandbState
from .utils import log_info, mean, median, write_jsonl


def mouse_episode_duration_ms(episode: MouseEpisode) -> float:
    return sum(step.dt_ms for step in episode.steps)


def path_length(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        math.hypot(current[0] - previous[0], current[1] - previous[1])
        for previous, current in pairwise(points)
    )


def click_rollout_record(
    model: MouseTrajectoryGRU,
    episode: MouseEpisode,
    index: int,
    coordinate_scale: float,
    position_frame: str,
    actions: list[str],
    device: torch.device,
    max_steps: int,
    click_threshold: float,
    min_dt_ms: float,
) -> dict[str, Any]:
    sim_rows = simulate_mouse_click_rows(
        model=model,
        episode=episode,
        coordinate_scale=coordinate_scale,
        position_frame=position_frame,
        actions=actions,
        device=device,
        max_steps=max_steps,
        click_threshold=click_threshold,
        min_dt_ms=min_dt_ms,
    )
    real_points = [(episode.start_x, episode.start_y)] + [(step.x, step.y) for step in episode.steps]
    sim_points = [(episode.start_x, episode.start_y)] + [
        (float(row["x"]), float(row["y"]))
        for row in sim_rows
    ]
    real_duration_ms = mouse_episode_duration_ms(episode)
    sim_duration_ms = float(sim_rows[-1]["offsetMs"]) if sim_rows else 0.0
    distance_px = math.hypot(episode.dst_x - episode.start_x, episode.dst_y - episode.start_y)
    endpoint_error_px = (
        math.hypot(float(sim_rows[-1]["x"]) - episode.dst_x, float(sim_rows[-1]["y"]) - episode.dst_y)
        if sim_rows
        else distance_px
    )
    duration_ratio = sim_duration_ms / real_duration_ms if real_duration_ms > 0 else float("nan")
    return {
        "index": index,
        "source": episode.source,
        "distance_px": distance_px,
        "real_duration_ms": real_duration_ms,
        "sim_duration_ms": sim_duration_ms,
        "duration_error_ms": sim_duration_ms - real_duration_ms,
        "abs_duration_error_ms": abs(sim_duration_ms - real_duration_ms),
        "duration_ratio": duration_ratio,
        "real_steps": len(episode.steps),
        "sim_steps": len(sim_rows),
        "real_path_px": path_length(real_points),
        "sim_path_px": path_length(sim_points),
        "endpoint_error_px": endpoint_error_px,
        "sim_clicked": bool(sim_rows and sim_rows[-1]["action"] != "move"),
        "sim_final_action": str(sim_rows[-1]["action"]) if sim_rows else "none",
    }


def log_click_rollout_diagnostics(
    model: MouseTrajectoryGRU,
    episodes: list[MouseEpisode],
    coordinate_scale: float,
    run_dir: Path,
    device: torch.device,
    wandb_state: WandbState | None,
    max_examples: int,
    max_steps: int,
    click_threshold: float,
    min_dt_ms: float,
) -> None:
    if max_examples <= 0 or not episodes:
        return

    examples = episodes[:max_examples]
    was_training = model.training
    model.eval()
    records = [
        click_rollout_record(
            model=model,
            episode=episode,
            index=index,
            coordinate_scale=coordinate_scale,
            position_frame="goal_relative_delta",
            actions=MOUSE_ACTIONS,
            device=device,
            max_steps=max_steps,
            click_threshold=click_threshold,
            min_dt_ms=min_dt_ms,
        )
        for index, episode in enumerate(examples)
    ]
    if was_training:
        model.train()

    diagnostics_path = run_dir / "click_rollout_diagnostics.jsonl"
    for record in records:
        write_jsonl(diagnostics_path, record)
    log_info(f"click_rollout_diagnostics={diagnostics_path} examples={len(records)}")

    numeric_keys = [
        "distance_px",
        "real_duration_ms",
        "sim_duration_ms",
        "duration_error_ms",
        "abs_duration_error_ms",
        "duration_ratio",
        "real_steps",
        "sim_steps",
        "real_path_px",
        "sim_path_px",
        "endpoint_error_px",
    ]
    summary: dict[str, float] = {"click_rollout/examples": float(len(records))}
    for key in numeric_keys:
        values = [
            float(record[key])
            for record in records
            if isinstance(record.get(key), int | float) and math.isfinite(float(record[key]))
        ]
        summary[f"click_rollout/{key}_mean"] = mean(values)
        summary[f"click_rollout/{key}_median"] = median(values)
    ratios = [
        float(record["duration_ratio"])
        for record in records
        if isinstance(record.get("duration_ratio"), int | float) and math.isfinite(float(record["duration_ratio"]))
    ]
    if ratios:
        summary["click_rollout/faster_than_real_fraction"] = sum(1.0 for ratio in ratios if ratio < 1.0) / len(ratios)

    if wandb_state is None:
        return

    columns = [
        "index",
        "source",
        "distance_px",
        "real_duration_ms",
        "sim_duration_ms",
        "duration_error_ms",
        "abs_duration_error_ms",
        "duration_ratio",
        "real_steps",
        "sim_steps",
        "real_path_px",
        "sim_path_px",
        "endpoint_error_px",
        "sim_clicked",
        "sim_final_action",
    ]
    table = wandb_state.module.Table(
        columns=columns,
        data=[[record.get(column) for column in columns] for record in records],
    )
    payload: dict[str, Any] = {
        "click_rollout/examples_table": table,
        **summary,
    }
    plot = getattr(wandb_state.module, "plot", None)
    if plot is not None:
        payload["click_rollout/real_vs_sim_duration"] = plot.scatter(
            table,
            "real_duration_ms",
            "sim_duration_ms",
            title="Click Duration: Real vs Simulated",
        )
        payload["click_rollout/duration_ratio_by_distance"] = plot.scatter(
            table,
            "distance_px",
            "duration_ratio",
            title="Click Duration Ratio by Distance",
        )
        payload["click_rollout/duration_error_histogram"] = plot.histogram(
            table,
            "duration_error_ms",
            title="Simulated Minus Real Click Duration",
        )
        payload["click_rollout/duration_ratio_histogram"] = plot.histogram(
            table,
            "duration_ratio",
            title="Simulated / Real Click Duration",
        )
    wandb_state.run.log(payload)
    for key, value in summary.items():
        wandb_state.run.summary[key] = value


def keyboard_rollout_record(
    checkpoint: dict,
    model: KeyboardActionGRU,
    episode: KeyboardEpisode,
    index: int,
    device: torch.device,
    sequence_mode: str,
    max_steps: int,
) -> dict[str, Any]:
    rows = decode_keyboard_rows(
        checkpoint=checkpoint,
        model=model,
        initial_string=episode.initial_string,
        final_string=episode.final_string,
        device=device,
        max_steps=max(max_steps, len(terminal_edit_actions(episode.initial_string, episode.final_string)) + 1),
        decode_mode="constrained",
    )
    final_text = str(rows[-1]["textAfter"]) if rows else episode.initial_string
    real_duration_ms = keyboard_episode_duration_ms(episode, sequence_mode)
    sim_duration_ms = float(rows[-1]["offsetMs"]) if rows else 0.0
    duration_ratio = sim_duration_ms / real_duration_ms if real_duration_ms > 0 else None
    return {
        "index": index,
        "source": episode.source,
        "target": episode.final_string,
        "target_length": len(episode.final_string),
        "exact_match": final_text == episode.final_string,
        "real_duration_ms": real_duration_ms,
        "sim_duration_ms": sim_duration_ms,
        "duration_error_ms": sim_duration_ms - real_duration_ms,
        "abs_duration_error_ms": abs(sim_duration_ms - real_duration_ms),
        "duration_ratio": duration_ratio,
        "real_steps": len(canonical_keyboard_steps(episode) if sequence_mode == "constrained" else episode.steps),
        "sim_steps": len(rows),
        "final_text": final_text,
    }


def log_keyboard_rollout_diagnostics(
    checkpoint: dict,
    model: KeyboardActionGRU,
    episodes: list[KeyboardEpisode],
    run_dir: Path,
    device: torch.device,
    wandb_state: WandbState | None,
    sequence_mode: str,
    max_examples: int,
    max_steps: int,
) -> None:
    if max_examples <= 0 or not episodes:
        return

    examples = episodes[:max_examples]
    was_training = model.training
    model.eval()
    records: list[dict[str, Any]] = []
    skipped = 0
    for index, episode in enumerate(examples):
        try:
            records.append(
                keyboard_rollout_record(
                    checkpoint=checkpoint,
                    model=model,
                    episode=episode,
                    index=index,
                    device=device,
                    sequence_mode=sequence_mode,
                    max_steps=max_steps,
                )
            )
        except (SystemExit, RuntimeError, ValueError) as exc:
            skipped += 1
            write_jsonl(
                run_dir / "keyboard_rollout_diagnostics_skipped.jsonl",
                {
                    "index": index,
                    "source": episode.source,
                    "target": episode.final_string,
                    "error": str(exc),
                },
            )
    if was_training:
        model.train()
    if not records:
        log_info(f"keyboard_rollout_diagnostics_skipped={skipped} examples=0")
        return

    diagnostics_path = run_dir / "keyboard_rollout_diagnostics.jsonl"
    for record in records:
        write_jsonl(diagnostics_path, record)
    log_info(f"keyboard_rollout_diagnostics={diagnostics_path} examples={len(records)} skipped={skipped}")

    numeric_keys = [
        "target_length",
        "real_duration_ms",
        "sim_duration_ms",
        "duration_error_ms",
        "abs_duration_error_ms",
        "duration_ratio",
        "real_steps",
        "sim_steps",
    ]
    summary: dict[str, float] = {
        "keyboard_rollout/examples": float(len(records)),
        "keyboard_rollout/exact_match_fraction": (
            sum(1.0 for record in records if record["exact_match"]) / len(records)
            if records
            else float("nan")
        ),
    }
    for key in numeric_keys:
        values = [
            float(record[key])
            for record in records
            if isinstance(record.get(key), int | float) and math.isfinite(float(record[key]))
        ]
        summary[f"keyboard_rollout/{key}_mean"] = mean(values)
        summary[f"keyboard_rollout/{key}_median"] = median(values)
    ratios = [
        float(record["duration_ratio"])
        for record in records
        if isinstance(record.get("duration_ratio"), int | float) and math.isfinite(float(record["duration_ratio"]))
    ]
    if ratios:
        summary["keyboard_rollout/faster_than_real_fraction"] = sum(1.0 for ratio in ratios if ratio < 1.0) / len(ratios)

    if wandb_state is None:
        return

    columns = [
        "index",
        "source",
        "target",
        "target_length",
        "exact_match",
        "real_duration_ms",
        "sim_duration_ms",
        "duration_error_ms",
        "abs_duration_error_ms",
        "duration_ratio",
        "real_steps",
        "sim_steps",
        "final_text",
    ]
    table = wandb_state.module.Table(
        columns=columns,
        data=[[record.get(column) for column in columns] for record in records],
    )
    payload: dict[str, Any] = {
        "keyboard_rollout/examples_table": table,
        **summary,
    }
    plot = getattr(wandb_state.module, "plot", None)
    if plot is not None:
        payload["keyboard_rollout/real_vs_sim_duration"] = plot.scatter(
            table,
            "real_duration_ms",
            "sim_duration_ms",
            title="Keyboard Duration: Real vs Simulated",
        )
        payload["keyboard_rollout/duration_ratio_by_length"] = plot.scatter(
            table,
            "target_length",
            "duration_ratio",
            title="Keyboard Duration Ratio by Target Length",
        )
        payload["keyboard_rollout/duration_error_histogram"] = plot.histogram(
            table,
            "duration_error_ms",
            title="Simulated Minus Real Keyboard Duration",
        )
        payload["keyboard_rollout/duration_ratio_histogram"] = plot.histogram(
            table,
            "duration_ratio",
            title="Simulated / Real Keyboard Duration",
        )
    wandb_state.run.log(payload)
    for key, value in summary.items():
        wandb_state.run.summary[key] = value
