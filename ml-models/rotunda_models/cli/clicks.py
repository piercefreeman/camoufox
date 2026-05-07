"""CLI wiring for mouse click cadence commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from ..generation import load_checkpoint, simulate_mouse_click_rows
from ..models.mouse import MouseTrajectoryGRU
from ..types import MouseEpisode


def generate_click(args: argparse.Namespace) -> None:
    """Print generated mouse click rows as JSON for CLI callers."""
    device = torch.device(args.device if args.device else "cpu")
    checkpoint = load_checkpoint(args.checkpoint, device)
    if checkpoint.get("kind") != "mouse_click_gru":
        raise SystemExit(f"Expected mouse_click_gru checkpoint, got {checkpoint.get('kind')!r}")
    model = MouseTrajectoryGRU(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    episode = MouseEpisode(
        source="generated",
        start_x=args.current_x,
        start_y=args.current_y,
        dst_x=args.dst_x,
        dst_y=args.dst_y,
        steps=(),
    )
    rows = simulate_mouse_click_rows(
        model=model,
        episode=episode,
        coordinate_scale=float(checkpoint["coordinate_scale"]),
        position_frame=checkpoint.get("position_frame", "screen_delta"),
        actions=checkpoint["actions"],
        device=device,
        max_steps=args.max_steps,
        click_threshold=args.click_threshold,
        min_dt_ms=args.min_dt_ms,
        endpoint_guidance=args.endpoint_guidance,
        sample=args.sample,
        temperature=args.temperature,
    )
    for row in rows:
        row["offsetMs"] = round(float(row["offsetMs"]), 3)
        row["dtMs"] = round(float(row["dtMs"]), 3)

    print(json.dumps(rows, indent=2))


def add_click_parsers(subparsers: argparse._SubParsersAction) -> None:
    click_generate = subparsers.add_parser("generate-click", help="Generate mouse positions/actions from a click checkpoint.")
    click_generate.add_argument("--checkpoint", type=Path, required=True)
    click_generate.add_argument("--current-x", type=float, required=True)
    click_generate.add_argument("--current-y", type=float, required=True)
    click_generate.add_argument("--dst-x", type=float, required=True)
    click_generate.add_argument("--dst-y", type=float, required=True)
    click_generate.add_argument("--max-steps", type=int, default=128)
    click_generate.add_argument("--sample", action="store_true")
    click_generate.add_argument("--temperature", type=float, default=1.0)
    click_generate.add_argument("--endpoint-guidance", action=argparse.BooleanOptionalAction, default=True)
    click_generate.add_argument("--click-threshold", type=float, default=0.98)
    click_generate.add_argument("--min-dt-ms", type=float, default=4.0)
    click_generate.add_argument("--device", default=None)
    click_generate.set_defaults(func=generate_click)
