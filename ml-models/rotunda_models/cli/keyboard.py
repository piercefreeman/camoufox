"""CLI wiring for keyboard cadence commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from ..constants import DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS
from ..generation import decode_keyboard_rows, load_checkpoint
from ..models.keyboard import KeyboardActionGRU


def generate_keyboard(args: argparse.Namespace) -> None:
    """Print generated keyboard rows as JSON for CLI callers."""
    device = torch.device(args.device if args.device else "cpu")
    checkpoint = load_checkpoint(args.checkpoint, device)
    if checkpoint.get("kind") != "keyboard_action_gru":
        raise SystemExit(f"Expected keyboard_action_gru checkpoint, got {checkpoint.get('kind')!r}")

    # Keep CLI concerns here: load the checkpoint/model, pass decoded settings to
    # generation.py, then format the resulting rows for stdout.
    model = KeyboardActionGRU(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    rows = decode_keyboard_rows(
        checkpoint=checkpoint,
        model=model,
        initial_string=args.initial_string,
        final_string=args.final_string,
        device=device,
        max_steps=args.max_steps,
        decode_mode=args.decode_mode,
        sample=args.sample,
        temperature=args.temperature,
        structured_extra_steps=args.keyboard_structured_extra_steps,
        canonical_bias=args.keyboard_canonical_bias,
        typo_rate=args.keyboard_typo_rate,
        max_typos=args.keyboard_max_typos,
        typo_seed=args.keyboard_typo_seed,
        typo_mode_weights=args.keyboard_typo_mode_weights,
        max_typo_chars=args.keyboard_max_typo_chars,
        max_backtrack_chars=args.keyboard_max_backtrack_chars,
        typo_min_dt_ms=args.keyboard_typo_min_dt_ms,
    )
    for row in rows:
        row["offsetMs"] = round(float(row["offsetMs"]), 3)
        row["dtMs"] = round(float(row["dtMs"]), 3)
    print(json.dumps(rows, indent=2))


def add_keyboard_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register keyboard generation commands on the shared CLI parser."""
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
