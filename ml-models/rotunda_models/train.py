#!/usr/bin/env python3
"""Train and inspect Rotunda cadence models from recorder NDJSON files."""

from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader

from ._generated_data_capture import SessionStartedEvent, SessionStoppedEvent
from .constants import MOUSE_ACTIONS
from .data import (
    event_screen_size,
    extract_focused_text_keyboard_episodes,
    extract_mouse_episodes,
    iter_capture_events,
    screen_filter_allows,
)
from .diagnostics import log_click_rollout_diagnostics, log_keyboard_rollout_diagnostics
from .models.keyboard import (
    KeyboardActionGRU,
    KeyboardTrajectoryDataset,
    collate_keyboard,
    keyboard_loss,
)
from .models.mouse import (
    MouseTrajectoryDataset,
    MouseTrajectoryGRU,
    collate_mouse,
    mouse_loss,
)
from .settings import TrainingExperimentSettings, load_experiment_settings
from .training_utils import (
    aggregate_metrics,
    build_keyboard_vocabs,
    coordinate_scale_for,
    filter_keyboard_training_episodes,
    keyboard_condition_length,
    move_batch_to_device,
    split_items,
)
from .types import ScreenSizeFilter, WandbState
from .utils import (
    discover_recording_paths,
    log_epoch,
    log_info,
    log_stage,
    make_run_dir,
    namespace_config,
    write_jsonl,
)
from .wandb import (
    finish_wandb_run,
    start_wandb_run,
    wandb_log_artifacts,
    wandb_log_epoch,
)


def training_namespace(
    args: Any | TrainingExperimentSettings,
    task: str,
) -> Any:
    """Resolve CLI/config settings into the flat namespace used by trainers."""
    if isinstance(args, TrainingExperimentSettings):
        return args.to_namespace(task)  # type: ignore[arg-type]
    config_path = getattr(args, "config", None)
    if config_path is not None:
        return load_experiment_settings(Path(config_path)).to_namespace(task)  # type: ignore[arg-type]
    if not hasattr(args, "screen_filter"):
        args.screen_filter = ScreenSizeFilter()
    if not hasattr(args, "experiment_name"):
        args.experiment_name = None
    return args


def train_experiment(args: Any) -> None:
    """Run the task or tasks declared by a YAML experiment config."""
    settings = load_experiment_settings(args.config)
    # A single config can intentionally train both models; task-specific
    # namespaces are derived inside train_clicks/train_keyboard.
    if settings.task in {"all", "clicks"}:
        train_clicks(settings)
    if settings.task in {"all", "keyboard"}:
        train_keyboard(settings)


def train_loop(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader | None,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    epochs: int,
    run_dir: Path,
    loss_fn,
    checkpoint_payload,
    early_stopping_patience: int = 0,
    early_stopping_min_delta: float = 0.0,
    wandb_state: WandbState | None = None,
    wandb_task: str | None = None,
    wandb_log_model_artifacts: bool = True,
) -> None:
    """Train a model, persist epoch checkpoints, and emit optional W&B logs."""
    metrics_path = run_dir / "metrics.jsonl"
    log_stage("training")
    best_score = float("inf")
    best_epoch = 0
    epochs_without_improvement = 0
    for epoch in range(1, epochs + 1):
        # Run one optimizer pass over the training split and keep scalar loss
        # pieces so local metrics and W&B receive the same view of the epoch.
        model.train()
        train_records: list[dict[str, float]] = []
        for batch in train_loader:
            batch = move_batch_to_device(batch, device)
            optimizer.zero_grad(set_to_none=True)
            loss, metrics = loss_fn(batch, model)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_records.append(metrics)

        train_metrics = aggregate_metrics(train_records)
        val_metrics: dict[str, float] = {}
        if val_loader is not None:
            # Validation reuses the same loss function but does not touch model
            # state, which keeps early stopping tied to the deployed objective.
            model.eval()
            val_records: list[dict[str, float]] = []
            with torch.no_grad():
                for batch in val_loader:
                    batch = move_batch_to_device(batch, device)
                    _, metrics = loss_fn(batch, model)
                    val_records.append(metrics)
            val_metrics = aggregate_metrics(val_records)

        record = {"epoch": epoch, "train": train_metrics, "val": val_metrics}
        write_jsonl(metrics_path, record)
        log_epoch(
            epoch,
            train_metrics.get("loss", float("nan")),
            val_metrics.get("loss") if val_metrics else None,
        )

        checkpoint = checkpoint_payload()
        checkpoint["model_state"] = model.state_dict()
        checkpoint["last_epoch"] = epoch
        torch.save(checkpoint, run_dir / "model.pt")
        score = val_metrics.get("loss", train_metrics.get("loss", float("inf")))
        improved = score < (best_score - early_stopping_min_delta)
        if improved:
            # Persist the best checkpoint separately so later generation can use
            # validation selection without parsing metrics.jsonl.
            best_score = score
            best_epoch = epoch
            epochs_without_improvement = 0
            checkpoint["best_epoch"] = best_epoch
            checkpoint["best_score"] = best_score
            torch.save(checkpoint, run_dir / "model-best.pt")
        else:
            epochs_without_improvement += 1
        lr = optimizer.param_groups[0].get("lr") if optimizer.param_groups else None
        wandb_log_epoch(
            wandb_state,
            epoch=epoch,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            score=score,
            best_score=best_score,
            best_epoch=best_epoch,
            lr=float(lr) if lr is not None else None,
        )

        if early_stopping_patience > 0 and epochs_without_improvement >= early_stopping_patience:
            stop_record = {
                "early_stopped": True,
                "epoch": epoch,
                "best_epoch": best_epoch,
                "best_score": best_score,
                "patience": early_stopping_patience,
                "min_delta": early_stopping_min_delta,
            }
            write_jsonl(metrics_path, stop_record)
            log_stage(
                "early stopping "
                f"epoch={epoch} best_epoch={best_epoch} best_loss={best_score:.4f}"
            )
            if wandb_state is not None:
                wandb_state.run.summary["early_stopped"] = True
                wandb_state.run.summary["stopped_epoch"] = epoch
            break

    log_stage(f"checkpoint saved: {run_dir / 'model.pt'}")
    if best_epoch:
        log_stage(f"best checkpoint saved: {run_dir / 'model-best.pt'} epoch={best_epoch} loss={best_score:.4f}")
    if wandb_state is not None:
        wandb_state.run.summary["best/loss"] = best_score
        wandb_state.run.summary["best/epoch"] = best_epoch
        if wandb_log_model_artifacts:
            wandb_log_artifacts(wandb_state, wandb_task or "cadence", run_dir)


def train_clicks(args: Any | TrainingExperimentSettings) -> None:
    """Train the mouse click trajectory model from configured recordings."""
    args = training_namespace(args, "clicks")
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Discover recorder outputs first so downstream metadata records the exact
    # files used for this run.
    log_stage("loading recordings")
    paths = discover_recording_paths(args.inputs)
    if not paths:
        raise SystemExit("No .ndjson or .jsonl recordings found.")
    log_info(f"recording_files={len(paths)}")

    # Convert raw mouse movement into episodes that start after pointer rest and
    # terminate on a single click near the requested destination.
    log_stage("building motivated click episodes")
    episodes = extract_mouse_episodes(
        paths,
        rest_ms=args.rest_ms,
        max_duration_ms=args.max_duration_ms,
        min_distance=args.min_distance,
        screen_filter=args.screen_filter,
    )
    if not episodes:
        raise SystemExit("No motivated click episodes found with the current filters.")
    scale = coordinate_scale_for(episodes)
    lengths = [len(episode.steps) for episode in episodes]
    log_info(
        f"episodes={len(episodes)} steps_avg={sum(lengths) / len(lengths):.1f} "
        f"steps_max={max(lengths)} coordinate_scale={scale:.1f}"
    )

    # Materialize train/validation datasets before constructing the model so
    # dimensions and coordinate scale come directly from the extracted data.
    log_stage("splitting data")
    train_episodes, val_episodes = split_items(episodes, args.val_fraction, args.seed)
    train_dataset = MouseTrajectoryDataset(train_episodes, coordinate_scale=scale)
    val_dataset = MouseTrajectoryDataset(val_episodes, coordinate_scale=scale) if val_episodes else None
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate_mouse)
    val_loader = (
        DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, collate_fn=collate_mouse)
        if val_dataset is not None
        else None
    )
    log_info(f"train={len(train_dataset)} val={0 if val_dataset is None else len(val_dataset)}")

    # The click model is intentionally compact: a conditioned recurrent decoder
    # with separate timing, position, and action heads.
    log_stage("initializing model")
    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    model_config = {
        "condition_dim": 7,
        "previous_dim": 3 + len(MOUSE_ACTIONS) + 1,
        "hidden_size": args.hidden_size,
        "action_count": len(MOUSE_ACTIONS),
        "layers": args.layers,
        "dropout": args.dropout,
    }
    model = MouseTrajectoryGRU(**model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    run_dir = make_run_dir(args.output_dir, "clicks")
    log_info(f"device={device} run_dir={run_dir}")

    config = namespace_config(args)
    config["inputs"] = [str(path) for path in paths]
    write_jsonl(run_dir / "metrics.jsonl", {"config": config, "episode_count": len(episodes)})
    wandb_state = start_wandb_run(
        args,
        task="clicks",
        run_dir=run_dir,
        config=config,
        metadata={
            "episode_count": len(episodes),
            "recording_files": len(paths),
            "train_count": len(train_dataset),
            "val_count": 0 if val_dataset is None else len(val_dataset),
            "coordinate_scale": scale,
            "steps_avg": sum(lengths) / len(lengths),
            "steps_max": max(lengths),
        },
    )
    if wandb_state is not None and getattr(args, "wandb_watch", False):
        wandb_state.module.watch(model, log="gradients", log_freq=100)

    # Save a checkpoint payload factory so each epoch writes architecture,
    # vocabularies, and training config next to the model weights.
    def checkpoint_payload() -> dict:
        return {
            "kind": "mouse_click_gru",
            "model_config": model_config,
            "actions": MOUSE_ACTIONS,
            "coordinate_scale": scale,
            "position_frame": "goal_relative_delta",
            "training_config": config,
        }

    try:
        train_loop(
            model=model,
            train_loader=train_loader,
            val_loader=val_loader,
            optimizer=optimizer,
            device=device,
            epochs=args.epochs,
            run_dir=run_dir,
            loss_fn=lambda batch, model: mouse_loss(
                batch,
                model,
                dt_weight=args.dt_loss_weight,
                pos_weight=args.pos_loss_weight,
                click_action_weight=args.click_action_weight,
                duration_weight=args.click_duration_loss_weight,
            ),
            checkpoint_payload=checkpoint_payload,
            early_stopping_patience=args.early_stopping_patience,
            early_stopping_min_delta=args.early_stopping_min_delta,
            wandb_state=wandb_state,
            wandb_task="clicks",
            wandb_log_model_artifacts=args.wandb_log_artifacts,
        )
        log_click_rollout_diagnostics(
            model=model,
            episodes=val_episodes or train_episodes,
            coordinate_scale=scale,
            run_dir=run_dir,
            device=device,
            wandb_state=wandb_state,
            max_examples=args.wandb_click_rollout_examples,
            max_steps=args.wandb_click_rollout_max_steps,
            click_threshold=args.wandb_click_rollout_click_threshold,
            min_dt_ms=args.wandb_click_rollout_min_dt_ms,
        )
    finally:
        finish_wandb_run(wandb_state)


def train_keyboard(args: Any | TrainingExperimentSettings) -> None:
    """Train the keyboard action model from focused accessibility text."""
    args = training_namespace(args, "keyboard")
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Load concrete recording files now; generated checkpoints store this list
    # rather than the original glob-like CLI inputs.
    log_stage("loading recordings")
    paths = discover_recording_paths(args.inputs)
    if not paths:
        raise SystemExit("No .ndjson or .jsonl recordings found.")
    log_info(f"recording_files={len(paths)}")

    # Current recordings carry the focused accessibility value, so keyboard
    # training is a direct text-diff problem rather than key-geometry recovery.
    log_stage("building keyboard episodes")
    episodes, focused_text_meta = extract_focused_text_keyboard_episodes(
        paths,
        gap_ms=args.gap_ms,
        accessibility_id=args.keyboard_accessibility_id,
        max_snapshot_edit_actions=args.keyboard_max_snapshot_edit_actions,
        screen_filter=args.screen_filter,
    )
    if not episodes:
        raise SystemExit("No focused-text keyboard episodes found with the current filters.")
    keyboard_sequence_mode = "raw"
    selected = focused_text_meta.get("selected_focused_text_identity", "unknown")
    log_info(
        f"focused_text_episodes={len(episodes)} selected_identity={selected} "
        f"snapshots={focused_text_meta.get('selected_focused_text_snapshots', 0)}"
    )
    vocab_episodes = episodes
    if (
        args.keyboard_min_final_length > 0
        or args.keyboard_min_duration_ms > 0
        or args.keyboard_max_condition_length is not None
    ):
        before_filter = len(episodes)
        episodes = filter_keyboard_training_episodes(
            episodes,
            sequence_mode=keyboard_sequence_mode,
            min_final_length=args.keyboard_min_final_length,
            min_duration_ms=args.keyboard_min_duration_ms,
            max_condition_length=args.keyboard_max_condition_length,
        )
        log_info(
            f"filtered_keyboard_episodes={len(episodes)} from={before_filter} "
            f"min_final_length={args.keyboard_min_final_length} "
            f"min_duration_ms={args.keyboard_min_duration_ms:g} "
            f"max_condition_length={args.keyboard_max_condition_length or 'none'}"
        )
        if not episodes:
            raise SystemExit("No keyboard episodes remain after the current training filters.")
    lengths = [len(episode.steps) for episode in episodes]
    condition_lengths = [keyboard_condition_length(episode) for episode in episodes]
    log_info(
        f"episodes={len(episodes)} steps_avg={sum(lengths) / len(lengths):.1f} "
        f"steps_max={max(lengths)} condition_max={max(condition_lengths)} "
        f"source=focused_text sequence_mode={keyboard_sequence_mode}"
    )

    # Build vocabularies from the unfiltered candidate set so generation can
    # still emit characters seen in valid source data but filtered from training.
    log_stage("building vocabularies and splitting data")
    char_to_id, action_to_id = build_keyboard_vocabs(vocab_episodes)
    id_to_char = {index: token for token, index in char_to_id.items()}
    id_to_action = {index: token for token, index in action_to_id.items()}
    train_episodes, val_episodes = split_items(episodes, args.val_fraction, args.seed)
    train_dataset = KeyboardTrajectoryDataset(
        train_episodes,
        char_to_id=char_to_id,
        action_to_id=action_to_id,
        sequence_mode=keyboard_sequence_mode,
    )
    val_dataset = (
        KeyboardTrajectoryDataset(
            val_episodes,
            char_to_id=char_to_id,
            action_to_id=action_to_id,
            sequence_mode=keyboard_sequence_mode,
        )
        if val_episodes
        else None
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=lambda batch: collate_keyboard(batch, len(action_to_id)),
    )
    val_loader = (
        DataLoader(
            val_dataset,
            batch_size=args.batch_size,
            shuffle=False,
            collate_fn=lambda batch: collate_keyboard(batch, len(action_to_id)),
        )
        if val_dataset is not None
        else None
    )
    log_info(
        f"train={len(train_dataset)} val={0 if val_dataset is None else len(val_dataset)} "
        f"char_vocab={len(char_to_id)} action_vocab={len(action_to_id)}"
    )

    # The keyboard model uses a text encoder and recurrent action decoder with
    # explicit previous-action and next-target-character inputs.
    log_stage("initializing model")
    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    model_config = {
        "char_vocab_size": len(char_to_id),
        "action_vocab_size": len(action_to_id),
        "hidden_size": args.hidden_size,
        "char_embed_size": args.char_embed_size,
        "action_embed_size": args.action_embed_size,
        "layers": args.layers,
        "dropout": args.dropout,
    }
    model = KeyboardActionGRU(**model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    run_dir = make_run_dir(args.output_dir, "keyboard")
    log_info(f"device={device} run_dir={run_dir}")

    config = namespace_config(args)
    config["inputs"] = [str(path) for path in paths]
    config["keyboard_source"] = "focused_text"
    config["resolved_keyboard_sequence_mode"] = keyboard_sequence_mode
    config["focused_text"] = focused_text_meta
    write_jsonl(run_dir / "metrics.jsonl", {"config": config, "episode_count": len(episodes)})
    wandb_state = start_wandb_run(
        args,
        task="keyboard",
        run_dir=run_dir,
        config=config,
        metadata={
            "episode_count": len(episodes),
            "recording_files": len(paths),
            "train_count": len(train_dataset),
            "val_count": 0 if val_dataset is None else len(val_dataset),
            "char_vocab": len(char_to_id),
            "action_vocab": len(action_to_id),
            "steps_avg": sum(lengths) / len(lengths),
            "steps_max": max(lengths),
            "keyboard_source": "focused_text",
            "keyboard_sequence_mode": keyboard_sequence_mode,
        },
    )
    if wandb_state is not None and getattr(args, "wandb_watch", False):
        wandb_state.module.watch(model, log="gradients", log_freq=100)

    # Keep checkpoint metadata self-contained for generation, debug videos, and
    # sweeps without needing to reconstruct CLI defaults.
    def checkpoint_payload() -> dict:
        return {
            "kind": "keyboard_action_gru",
            "model_config": model_config,
            "char_to_id": char_to_id,
            "id_to_char": id_to_char,
            "action_to_id": action_to_id,
            "id_to_action": id_to_action,
            "training_config": config,
            "keyboard_source": "focused_text",
            "keyboard_sequence_mode": keyboard_sequence_mode,
        }

    try:
        train_loop(
            model=model,
            train_loader=train_loader,
            val_loader=val_loader,
            optimizer=optimizer,
            device=device,
            epochs=args.epochs,
            run_dir=run_dir,
            loss_fn=lambda batch, model: keyboard_loss(
                batch,
                model,
                dt_weight=args.dt_loss_weight,
                action_weight=args.keyboard_action_loss_weight,
                duration_weight=args.keyboard_duration_loss_weight,
                backspace_action_weight=args.backspace_action_weight,
                stop_action_weight=args.stop_action_weight,
            ),
            checkpoint_payload=checkpoint_payload,
            early_stopping_patience=args.early_stopping_patience,
            early_stopping_min_delta=args.early_stopping_min_delta,
            wandb_state=wandb_state,
            wandb_task="keyboard",
            wandb_log_model_artifacts=args.wandb_log_artifacts,
        )
        log_keyboard_rollout_diagnostics(
            checkpoint=checkpoint_payload(),
            model=model,
            episodes=val_episodes or train_episodes,
            run_dir=run_dir,
            device=device,
            wandb_state=wandb_state,
            sequence_mode=keyboard_sequence_mode,
            max_examples=args.wandb_keyboard_rollout_examples,
            max_steps=args.wandb_keyboard_rollout_max_steps,
        )
    finally:
        finish_wandb_run(wandb_state)


def inspect_recordings(args: Any) -> None:
    """Print corpus event counts and extractable episode counts as JSON."""
    if not hasattr(args, "screen_filter"):
        args.screen_filter = ScreenSizeFilter()
    paths = discover_recording_paths(args.inputs)
    if not paths:
        raise SystemExit("No .ndjson or .jsonl recordings found.")

    # Count raw and screen-filtered events in one pass so users can see how much
    # of the corpus survives the laptop-screen filter before training.
    counts: dict[str, int] = {}
    filtered_counts: dict[str, int] = {}
    screen_counts: dict[str, int] = {}
    current_screen_by_path: dict[str, tuple[int, int] | None] = {}
    for path, _, event in iter_capture_events(paths):
        event_type = event.type
        counts[event_type] = counts.get(event_type, 0) + 1
        screen_size = event_screen_size(event)
        path_key = str(path)
        if isinstance(event, SessionStartedEvent | SessionStoppedEvent):
            current_screen_by_path[path_key] = None
        if screen_size is not None:
            screen_counts[f"{screen_size[0]}x{screen_size[1]}"] = screen_counts.get(f"{screen_size[0]}x{screen_size[1]}", 0) + 1
            current_screen_by_path[path_key] = screen_size
        if screen_filter_allows(args.screen_filter, current_screen_by_path.get(path_key)):
            filtered_counts[event_type] = filtered_counts.get(event_type, 0) + 1

    mouse_episodes = extract_mouse_episodes(
        paths,
        rest_ms=args.rest_ms,
        max_duration_ms=args.max_duration_ms,
        min_distance=args.min_distance,
        screen_filter=args.screen_filter,
    )
    keyboard_episodes, focused_meta = extract_focused_text_keyboard_episodes(
        paths,
        gap_ms=args.gap_ms,
        accessibility_id=args.keyboard_accessibility_id,
        max_snapshot_edit_actions=args.keyboard_max_snapshot_edit_actions,
        screen_filter=args.screen_filter,
    )
    result = {
        "files": [str(path) for path in paths],
        "event_counts": counts,
        "screen_filtered_event_counts": filtered_counts,
        "screen_sizes": screen_counts,
        "screen_filter": namespace_config(SimpleNamespace(screen_filter=args.screen_filter))["screen_filter"],
        "motivated_click_episodes": len(mouse_episodes),
        "focused_text_keyboard_episodes": len(keyboard_episodes),
        "focused_text": focused_meta,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
