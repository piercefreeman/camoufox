"""Click commands for keyboard cadence generation."""

from __future__ import annotations

import json

import click
import torch

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
@click.option("--keyboard-structured-extra-steps", type=int, default=6, show_default=True, help="Extra learned edit steps allowed beyond the shortest path in constrained mode.")
@click.option("--keyboard-canonical-bias", type=float, default=3.0, show_default=True, help="Logit bias toward the shortest valid edit in constrained mode; higher is more structured, lower is more learned.")
@click.option("--keyboard-max-typos", type=int, default=2, show_default=True, help="Maximum learned typo events allowed during constrained keyboard generation.")
@click.option("--keyboard-typo-seed", type=int, default=13, show_default=True, help="Random seed for learned typo sampling.")
@click.option("--keyboard-learned-typo-threshold", type=float, default=0.2, show_default=True, help="Deterministic threshold for learned wrong-character emission in constrained mode.")
@click.option("--device", default=None)
def generate_keyboard_command(
    checkpoint,
    final_string: str,
    initial_string: str,
    max_steps: int,
    decode_mode: str,
    sample: bool,
    temperature: float,
    keyboard_structured_extra_steps: int,
    keyboard_canonical_bias: float,
    keyboard_max_typos: int,
    keyboard_typo_seed: int,
    keyboard_learned_typo_threshold: float,
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
        max_typos=keyboard_max_typos,
        typo_seed=keyboard_typo_seed,
        learned_typo_threshold=keyboard_learned_typo_threshold,
    )
    for row in rows:
        row["offsetMs"] = round(float(row["offsetMs"]), 3)
        row["dtMs"] = round(float(row["dtMs"]), 3)
    click.echo(json.dumps(rows, indent=2))
