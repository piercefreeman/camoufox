from __future__ import annotations

import unittest

from rotunda_models.constants import KEY_BACKSPACE, KEY_STOP
from rotunda_models.generation import structured_keyboard_action_ids


class KeyboardGenerationTests(unittest.TestCase):
    def test_structured_decode_does_not_backspace_valid_prefix(self) -> None:
        action_to_id = {"a": 0, "b": 1, "c": 2, KEY_BACKSPACE: 3, KEY_STOP: 4}

        valid_from_empty = structured_keyboard_action_ids(
            final_string="abc",
            text=[],
            action_to_id=action_to_id,
            remaining_steps_after_action=4,
        )
        valid_from_prefix = structured_keyboard_action_ids(
            final_string="abc",
            text=["a"],
            action_to_id=action_to_id,
            remaining_steps_after_action=3,
        )
        valid_from_mismatch = structured_keyboard_action_ids(
            final_string="abc",
            text=["a", "x"],
            action_to_id={**action_to_id, "x": 5},
            remaining_steps_after_action=2,
        )

        self.assertNotIn(action_to_id[KEY_BACKSPACE], valid_from_empty)
        self.assertNotIn(action_to_id[KEY_BACKSPACE], valid_from_prefix)
        self.assertIn(action_to_id[KEY_BACKSPACE], valid_from_mismatch)


if __name__ == "__main__":
    unittest.main()
