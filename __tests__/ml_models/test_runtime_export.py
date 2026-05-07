from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

import torch
from rotunda_models.constants import MOUSE_ACTIONS
from rotunda_models.models.keyboard import KeyboardActionGRU
from rotunda_models.models.mouse import MouseTrajectoryGRU
from rotunda_models.runtime_export import METADATA_KEY, export_runtime_checkpoint


class RuntimeExportTests(unittest.TestCase):
    def test_exports_mouse_checkpoint_as_safetensors(self) -> None:
        model = MouseTrajectoryGRU(
            condition_dim=7,
            previous_dim=3 + len(MOUSE_ACTIONS) + 1,
            hidden_size=8,
            action_count=len(MOUSE_ACTIONS),
            layers=1,
            dropout=0.0,
        )
        checkpoint = {
            "kind": "mouse_click_gru",
            "model_config": {
                "condition_dim": 7,
                "previous_dim": 3 + len(MOUSE_ACTIONS) + 1,
                "hidden_size": 8,
                "action_count": len(MOUSE_ACTIONS),
                "layers": 1,
                "dropout": 0.0,
            },
            "actions": MOUSE_ACTIONS,
            "coordinate_scale": 100.0,
            "position_frame": "goal_relative_delta",
            "model_state": model.state_dict(),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "model.pt"
            output_path = root / "mouse.safetensors"
            torch.save(checkpoint, checkpoint_path)

            result = export_runtime_checkpoint(checkpoint_path, output_path)

            data = output_path.read_bytes()
            header_len = struct.unpack("<Q", data[:8])[0]
            header = json.loads(data[8 : 8 + header_len].decode("utf-8"))
            metadata = json.loads(header["__metadata__"][METADATA_KEY])

        self.assertEqual(result["kind"], "mouse_click_gru")
        self.assertEqual(metadata["format"], "rotunda-runtime-v1")
        self.assertEqual(metadata["coordinateScale"], 100.0)
        self.assertIn("gru.weight_ih_l0", header)
        self.assertEqual(header["gru.weight_ih_l0"]["dtype"], "F32")

    def test_exports_keyboard_checkpoint_as_safetensors(self) -> None:
        char_to_id = {"<PAD>": 0, "<UNK>": 1, "<EOS>": 2, "<SEP>": 3, "h": 4}
        action_to_id = {"h": 0, "<BACKSPACE>": 1, "<STOP>": 2}
        id_to_action = {index: action for action, index in action_to_id.items()}
        model_config = {
            "char_vocab_size": len(char_to_id),
            "action_vocab_size": len(action_to_id),
            "hidden_size": 4,
            "char_embed_size": 3,
            "action_embed_size": 2,
            "layers": 1,
            "dropout": 0.0,
        }
        model = KeyboardActionGRU(**model_config)
        checkpoint = {
            "kind": "keyboard_action_gru",
            "model_config": model_config,
            "char_to_id": char_to_id,
            "action_to_id": action_to_id,
            "id_to_action": id_to_action,
            "sequence_mode": "constrained",
            "model_state": model.state_dict(),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_path = root / "model.pt"
            output_path = root / "keyboard.safetensors"
            torch.save(checkpoint, checkpoint_path)

            result = export_runtime_checkpoint(checkpoint_path, output_path)

            data = output_path.read_bytes()
            header_len = struct.unpack("<Q", data[:8])[0]
            header = json.loads(data[8 : 8 + header_len].decode("utf-8"))
            metadata = json.loads(header["__metadata__"][METADATA_KEY])

        self.assertEqual(result["kind"], "keyboard_action_gru")
        self.assertEqual(metadata["charToId"]["h"], 4)
        self.assertEqual(metadata["idToAction"]["2"], "<STOP>")
        self.assertIn("decoder.weight_ih_l0", header)


if __name__ == "__main__":
    unittest.main()
