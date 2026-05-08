"""Click commands for mouse click cadence generation."""

from __future__ import annotations

import json

import click
import torch

from ..generation import load_checkpoint, simulate_mouse_click_rows
from ..models.mouse import MouseTrajectoryGRU
from ..types import MouseEpisode
from .common import CONTEXT_SETTINGS, PATH_TYPE


@click.command(
    "generate-click",
    context_settings=CONTEXT_SETTINGS,
    help="Generate mouse positions/actions from a click checkpoint.",
)
@click.option("--checkpoint", type=PATH_TYPE, required=True)
@click.option("--current-x", type=float, required=True)
@click.option("--current-y", type=float, required=True)
@click.option("--dst-x", type=float, required=True)
@click.option("--dst-y", type=float, required=True)
@click.option("--max-steps", type=int, default=128, show_default=True)
@click.option("--sample", is_flag=True, default=False)
@click.option("--temperature", type=float, default=1.0, show_default=True)
@click.option("--endpoint-guidance/--no-endpoint-guidance", default=True, show_default=True)
@click.option("--click-threshold", type=float, default=0.98, show_default=True)
@click.option("--min-dt-ms", type=float, default=4.0, show_default=True)
@click.option("--device", default=None)
def generate_click_command(
    checkpoint,
    current_x: float,
    current_y: float,
    dst_x: float,
    dst_y: float,
    max_steps: int,
    sample: bool,
    temperature: float,
    endpoint_guidance: bool,
    click_threshold: float,
    min_dt_ms: float,
    device: str | None,
) -> None:
    """Print generated mouse click rows as JSON for CLI callers."""
    torch_device = torch.device(device if device else "cpu")
    checkpoint_data = load_checkpoint(checkpoint, torch_device)
    if checkpoint_data.get("kind") != "mouse_click_gru":
        raise click.ClickException(f"Expected mouse_click_gru checkpoint, got {checkpoint_data.get('kind')!r}")

    model = MouseTrajectoryGRU(**checkpoint_data["model_config"]).to(torch_device)
    model.load_state_dict(checkpoint_data["model_state"])
    model.eval()

    episode = MouseEpisode(
        source="generated",
        start_x=current_x,
        start_y=current_y,
        dst_x=dst_x,
        dst_y=dst_y,
        steps=(),
    )
    rows = simulate_mouse_click_rows(
        model=model,
        episode=episode,
        coordinate_scale=float(checkpoint_data["coordinate_scale"]),
        position_frame=checkpoint_data.get("position_frame", "screen_delta"),
        actions=checkpoint_data["actions"],
        device=torch_device,
        max_steps=max_steps,
        click_threshold=click_threshold,
        min_dt_ms=min_dt_ms,
        endpoint_guidance=endpoint_guidance,
        sample=sample,
        temperature=temperature,
    )
    for row in rows:
        row["offsetMs"] = round(float(row["offsetMs"]), 3)
        row["dtMs"] = round(float(row["dtMs"]), 3)

    click.echo(json.dumps(rows, indent=2))
