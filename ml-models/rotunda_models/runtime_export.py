"""Runtime checkpoint export for native Rotunda decoders."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import torch

from .generation import load_checkpoint

RUNTIME_FORMAT = "rotunda-runtime-v1"
METADATA_KEY = "rotunda_metadata"


def _metadata_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _tensor_payload(tensor: torch.Tensor) -> tuple[list[int], bytes]:
    cpu = tensor.detach().cpu().contiguous().to(torch.float32)
    shape = [int(dim) for dim in cpu.shape]
    return shape, cpu.numpy().tobytes(order="C")


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
                "sequenceMode": checkpoint.get("keyboard_sequence_mode", checkpoint.get("sequence_mode", "raw")),
                "learnedTypoHead": bool(checkpoint["model_config"].get("learned_typo_head", False)),
                "decodeDefaults": {
                    "mode": "constrained",
                    "structuredExtraSteps": 6,
                    "canonicalBias": 3.0,
                    "learnedTypoThreshold": 0.2,
                    "maxTypos": 2,
                },
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
