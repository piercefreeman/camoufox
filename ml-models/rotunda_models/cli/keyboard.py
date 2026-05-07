"""CLI wiring for keyboard cadence commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..constants import DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS
from ..generation import generate_keyboard


def add_keyboard_parsers(subparsers: argparse._SubParsersAction) -> None:
    keyboard_generate = subparsers.add_parser("generate-keyboard", help="Generate key actions from a keyboard checkpoint.")
    keyboard_generate.add_argument("--checkpoint", type=Path, required=True)
    keyboard_generate.add_argument("--final-string", required=True)
    keyboard_generate.add_argument("--initial-string", default="", help="Optional starting text for edit generation. Defaults to empty.")
    keyboard_generate.add_argument("--max-steps", type=int, default=256)
    keyboard_generate.add_argument("--decode-mode", choices=["constrained", "canonical", "unconstrained"], default="constrained", help="Constrained mode masks model logits to actions that can still reach --final-string. Canonical mode follows the shortest edit path. Unconstrained mode uses raw action logits.")
    keyboard_generate.add_argument("--sample", action="store_true")
    keyboard_generate.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature for unconstrained mode.")
    keyboard_generate.add_argument("--keyboard-typo-rate", type=float, default=0.0, help="Per-character probability of injecting a bounded correction event in constrained mode.")
    keyboard_generate.add_argument("--keyboard-structured-extra-steps", type=int, default=6, help="Extra learned edit steps allowed beyond the shortest path in constrained mode.")
    keyboard_generate.add_argument("--keyboard-canonical-bias", type=float, default=1.5, help="Logit bias toward the shortest valid edit in constrained mode; higher is more structured, lower is more learned.")
    keyboard_generate.add_argument("--keyboard-max-typos", type=int, default=2, help="Maximum correction events to inject during constrained keyboard generation.")
    keyboard_generate.add_argument("--keyboard-typo-seed", type=int, default=13, help="Random seed for constrained keyboard typo injection.")
    keyboard_generate.add_argument("--keyboard-typo-mode-weights", default=DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS, help="Comma-separated correction event weights, e.g. replace=0.55,forward=0.30,backtrack=0.15.")
    keyboard_generate.add_argument("--keyboard-max-typo-chars", type=int, default=3, help="Maximum wrong characters in one forward typo event.")
    keyboard_generate.add_argument("--keyboard-max-backtrack-chars", type=int, default=2, help="Maximum already-correct characters to backspace in one backtrack event.")
    keyboard_generate.add_argument("--keyboard-typo-min-dt-ms", type=float, default=20.0, help="Minimum delay for injected correction-event actions.")
    keyboard_generate.add_argument("--device", default=None)
    keyboard_generate.set_defaults(func=generate_keyboard)
