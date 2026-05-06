"""CLI wiring for keyboard cadence commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..constants import DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS
from ..generation import generate_keyboard
from ..train import train_keyboard
from .common import add_shared_training_args


def add_keyboard_parsers(subparsers: argparse._SubParsersAction) -> None:
    keyboard_parser = subparsers.add_parser("train-keyboard", help="Train the conditioned keyboard action GRU.")
    add_shared_training_args(keyboard_parser)
    keyboard_parser.add_argument("--gap-ms", type=int, default=1000)
    keyboard_parser.add_argument("--synthetic-per-sequence", type=int, default=4)
    keyboard_parser.add_argument("--geometry-tolerance", type=float, default=0.05)
    keyboard_parser.add_argument("--include-repeats", action="store_true")
    keyboard_parser.add_argument("--keyboard-text-source", choices=["auto", "focused", "synthetic"], default="auto", help="Use focused accessibility text when present, force it, or force synthetic physical-key reconstruction.")
    keyboard_parser.add_argument("--keyboard-accessibility-id", default="auto", help="Focused text accessibility id to train from. 'auto' selects the most active single element identity.")
    keyboard_parser.add_argument("--keyboard-max-snapshot-edit-actions", type=int, default=12, help="Focused text value jumps larger than this start a new segment.")
    keyboard_parser.add_argument("--keyboard-sequence-mode", choices=["auto", "constrained", "raw"], default="auto", help="Auto uses raw focused-text edits and constrained synthetic paths; override to force one mode.")
    keyboard_parser.add_argument("--keyboard-min-final-length", type=int, default=1, help="Drop shorter reconstructed keyboard episodes from training.")
    keyboard_parser.add_argument("--keyboard-min-duration-ms", type=float, default=0.0, help="Drop shorter-duration reconstructed keyboard episodes from training.")
    keyboard_parser.add_argument("--char-embed-size", type=int, default=32)
    keyboard_parser.add_argument("--action-embed-size", type=int, default=32)
    keyboard_parser.add_argument("--dt-loss-weight", type=float, default=1.0)
    keyboard_parser.add_argument("--keyboard-action-loss-weight", type=float, default=1.0)
    keyboard_parser.add_argument("--keyboard-duration-loss-weight", type=float, default=1.0)
    keyboard_parser.add_argument("--backspace-action-weight", type=float, default=4.0)
    keyboard_parser.add_argument("--stop-action-weight", type=float, default=8.0)
    keyboard_parser.add_argument("--wandb-keyboard-rollout-examples", type=int, default=128, help="Validation keyboard rollouts to chart in W&B after training. 0 disables this diagnostic.")
    keyboard_parser.add_argument("--wandb-keyboard-rollout-max-steps", type=int, default=256)
    keyboard_parser.set_defaults(func=train_keyboard)

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
