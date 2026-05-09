"""Runtime checkpoint export for native Rotunda decoders."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import torch

from .constants import KEY_BACKSPACE, KEY_UNKNOWN_ACTION
from .generation import load_checkpoint
from .keyboard_logic import minimum_terminal_edit_steps

RUNTIME_FORMAT = "rotunda-runtime-v1"
METADATA_KEY = "rotunda_metadata"


def _metadata_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _tensor_payload(tensor: torch.Tensor) -> tuple[list[int], bytes]:
    cpu = tensor.detach().cpu().contiguous().to(torch.float32)
    shape = [int(dim) for dim in cpu.shape]
    return shape, cpu.numpy().tobytes(order="C")


def _keyboard_decode_defaults_from_training_data(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Derive runtime decode slack from the same episodes used for training."""
    config = checkpoint.get("training_config")
    if not isinstance(config, dict) or not config.get("inputs"):
        return {}

    try:
        from .data import extract_keyboard_episodes
        from .training_utils import filter_keyboard_training_episodes
        from .types import ScreenSizeFilter

        screen_filter_config = config.get("screen_filter") or {}
        screen_filter = (
            screen_filter_config
            if isinstance(screen_filter_config, ScreenSizeFilter)
            else ScreenSizeFilter(**screen_filter_config)
        )
        episodes, _ = extract_keyboard_episodes(
            [Path(path) for path in config["inputs"]],
            gap_ms=int(config.get("gap_ms", 1000)),
            accessibility_id=config.get("keyboard_accessibility_id", "auto"),
            screen_filter=screen_filter,
        )
        sequence_mode = checkpoint.get(
            "keyboard_sequence_mode",
            config.get("resolved_keyboard_sequence_mode", "raw"),
        )
        episodes = filter_keyboard_training_episodes(
            episodes,
            sequence_mode=sequence_mode,
            min_final_length=int(config.get("keyboard_min_final_length", 1)),
            min_duration_ms=float(config.get("keyboard_min_duration_ms", 0.0)),
            max_condition_length=config.get("keyboard_max_condition_length"),
            max_steps=config.get("keyboard_max_steps"),
        )
    except Exception:
        return {}

    total_min_steps = 0
    total_extra_steps = 0
    total_backspaces = 0
    eligible = 0
    for episode in episodes:
        min_steps = minimum_terminal_edit_steps(episode.final_string, list(episode.initial_string))
        if min_steps <= 0:
            continue
        actual_steps = len(episode.steps)
        extra_steps = max(0, actual_steps - min_steps)
        total_min_steps += min_steps
        total_extra_steps += extra_steps
        total_backspaces += sum(1 for step in episode.steps if step.action == KEY_BACKSPACE)
        eligible += 1

    if total_min_steps <= 0:
        return {}

    return {
        "trainingEpisodeCount": eligible,
        "observedExtraStepRate": total_extra_steps / total_min_steps,
        "observedBackspaceRate": total_backspaces / total_min_steps,
        "observedMeanExtraSteps": total_extra_steps / max(1, eligible),
        "observedMeanBackspaces": total_backspaces / max(1, eligible),
    }


def keyboard_decode_defaults(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Return runtime keyboard decode defaults, preferring corpus-derived slack."""
    stats = _keyboard_decode_defaults_from_training_data(checkpoint)
    extra_step_rate = float(stats.get("observedExtraStepRate", 0.0))
    if not math.isfinite(extra_step_rate) or extra_step_rate <= 0.0:
        extra_step_rate = 0.03

    return {
        "mode": "constrained",
        "structuredExtraSteps": 6,
        "structuredExtraStepRate": extra_step_rate,
        "canonicalBias": 1.5,
        "learnedTypoThreshold": 0.05,
        "maxTypos": -1,
        "actionTemperature": 0.6,
        **stats,
    }


def safetensors_bytes(
    tensors: dict[str, torch.Tensor],
    metadata: dict[str, Any],
) -> bytes:
    """Serialize float tensors using the SafeTensors binary layout."""
    header: dict[str, Any] = {
        "__metadata__": {
            "format": RUNTIME_FORMAT,
            "kind": str(metadata.get("kind", "")),
            METADATA_KEY: _metadata_string(metadata),
        }
    }
    data_chunks: list[bytes] = []
    offset = 0
    for name in sorted(tensors):
        shape, payload = _tensor_payload(tensors[name])
        end = offset + len(payload)
        header[name] = {
            "dtype": "F32",
            "shape": shape,
            "data_offsets": [offset, end],
        }
        data_chunks.append(payload)
        offset = end

    header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack("<Q", len(header_bytes)) + header_bytes + b"".join(data_chunks)


def runtime_metadata(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Return compact metadata needed by native runtime decoders."""
    kind = checkpoint["kind"]
    metadata: dict[str, Any] = {
        "format": RUNTIME_FORMAT,
        "kind": kind,
        "modelConfig": checkpoint["model_config"],
    }
    if kind == "mouse_click_gru":
        metadata.update(
            {
                "actions": checkpoint["actions"],
                "coordinateScale": float(checkpoint["coordinate_scale"]),
                "positionFrame": checkpoint.get("position_frame", "screen_delta"),
            }
        )
    elif kind == "keyboard_action_gru":
        metadata.update(
            {
                "charToId": checkpoint["char_to_id"],
                "idToAction": {str(index): token for index, token in checkpoint["id_to_action"].items()},
                "actionToId": checkpoint.get("action_to_id")
                or {token: int(index) for index, token in checkpoint["id_to_action"].items()},
                "unknownAction": KEY_UNKNOWN_ACTION,
                "sequenceMode": checkpoint.get("keyboard_sequence_mode", checkpoint.get("sequence_mode", "raw")),
                "learnedTypoHead": bool(checkpoint["model_config"].get("learned_typo_head", False)),
                "decodeDefaults": keyboard_decode_defaults(checkpoint),
            }
        )
    else:
        raise ValueError(f"Unsupported runtime checkpoint kind: {kind!r}")
    return metadata


def export_runtime_checkpoint(checkpoint_path: Path, output_path: Path, device: str | None = None) -> dict[str, Any]:
    """Export one PyTorch checkpoint to a SafeTensors runtime artifact."""
    torch_device = torch.device(device if device else "cpu")
    checkpoint = load_checkpoint(checkpoint_path, torch_device)
    if "model_state" not in checkpoint:
        raise ValueError(f"{checkpoint_path} does not contain model_state.")
    metadata = runtime_metadata(checkpoint)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(safetensors_bytes(checkpoint["model_state"], metadata))
    return {
        "kind": metadata["kind"],
        "path": str(output_path),
        "tensorCount": len(checkpoint["model_state"]),
        "metadata": metadata,
    }
