"""Click commands for keyboard cadence generation."""

from __future__ import annotations

import json

import click
import torch

from ..constants import DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS
from ..generation import decode_keyboard_rows, load_checkpoint
from ..models.keyboard import KeyboardActionGRU
from .common import CONTEXT_SETTINGS, PATH_TYPE


@click.command(
    "generate-keyboard",
    context_settings=CONTEXT_SETTINGS,
    help="Generate key actions from a keyboard checkpoint.",
)
@click.option("--checkpoint", type=PATH_TYPE, required=True)
@click.option("--final-string", required=True)
@click.option("--initial-string", default="", help="Optional starting text for edit generation. Defaults to empty.")
@click.option("--max-steps", type=int, default=256, show_default=True)
@click.option(
    "--decode-mode",
    type=click.Choice(["constrained", "canonical", "unconstrained"]),
    default="constrained",
    show_default=True,
    help="Constrained mode masks model logits to actions that can still reach --final-string. Canonical mode follows the shortest edit path. Unconstrained mode uses raw action logits.",
)
@click.option("--sample", is_flag=True, default=False)
@click.option("--temperature", type=float, default=1.0, show_default=True, help="Sampling temperature for unconstrained mode.")
@click.option("--keyboard-typo-rate", type=float, default=0.0, show_default=True, help="Per-character probability of injecting a bounded correction event in constrained mode.")
@click.option("--keyboard-structured-extra-steps", type=int, default=6, show_default=True, help="Extra learned edit steps allowed beyond the shortest path in constrained mode.")
@click.option("--keyboard-canonical-bias", type=float, default=1.5, show_default=True, help="Logit bias toward the shortest valid edit in constrained mode; higher is more structured, lower is more learned.")
@click.option("--keyboard-max-typos", type=int, default=2, show_default=True, help="Maximum correction events to inject during constrained keyboard generation.")
@click.option("--keyboard-typo-seed", type=int, default=13, show_default=True, help="Random seed for constrained keyboard typo injection.")
@click.option("--keyboard-typo-mode-weights", default=DEFAULT_KEYBOARD_TYPO_MODE_WEIGHTS, show_default=True, help="Comma-separated correction event weights, e.g. replace=0.55,forward=0.30,backtrack=0.15.")
@click.option("--keyboard-max-typo-chars", type=int, default=3, show_default=True, help="Maximum wrong characters in one forward typo event.")
@click.option("--keyboard-max-backtrack-chars", type=int, default=2, show_default=True, help="Maximum already-correct characters to backspace in one backtrack event.")
@click.option("--keyboard-typo-min-dt-ms", type=float, default=20.0, show_default=True, help="Minimum delay for injected correction-event actions.")
@click.option("--device", default=None)
def generate_keyboard_command(
    checkpoint,
    final_string: str,
    initial_string: str,
    max_steps: int,
    decode_mode: str,
    sample: bool,
    temperature: float,
    keyboard_typo_rate: float,
    keyboard_structured_extra_steps: int,
    keyboard_canonical_bias: float,
    keyboard_max_typos: int,
    keyboard_typo_seed: int,
    keyboard_typo_mode_weights: str,
    keyboard_max_typo_chars: int,
    keyboard_max_backtrack_chars: int,
    keyboard_typo_min_dt_ms: float,
    device: str | None,
) -> None:
    """Print generated keyboard rows as JSON for CLI callers."""
    torch_device = torch.device(device if device else "cpu")
    checkpoint_data = load_checkpoint(checkpoint, torch_device)
    if checkpoint_data.get("kind") != "keyboard_action_gru":
        raise click.ClickException(f"Expected keyboard_action_gru checkpoint, got {checkpoint_data.get('kind')!r}")

    model = KeyboardActionGRU(**checkpoint_data["model_config"]).to(torch_device)
    model.load_state_dict(checkpoint_data["model_state"])
    model.eval()

    rows = decode_keyboard_rows(
        checkpoint=checkpoint_data,
        model=model,
        initial_string=initial_string,
        final_string=final_string,
        device=torch_device,
        max_steps=max_steps,
        decode_mode=decode_mode,
        sample=sample,
        temperature=temperature,
        structured_extra_steps=keyboard_structured_extra_steps,
        canonical_bias=keyboard_canonical_bias,
        typo_rate=keyboard_typo_rate,
        max_typos=keyboard_max_typos,
        typo_seed=keyboard_typo_seed,
        typo_mode_weights=keyboard_typo_mode_weights,
        max_typo_chars=keyboard_max_typo_chars,
        max_backtrack_chars=keyboard_max_backtrack_chars,
        typo_min_dt_ms=keyboard_typo_min_dt_ms,
    )
    for row in rows:
        row["offsetMs"] = round(float(row["offsetMs"]), 3)
        row["dtMs"] = round(float(row["dtMs"]), 3)
    click.echo(json.dumps(rows, indent=2))
