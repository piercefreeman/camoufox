"""CLI wiring for mouse click cadence commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..generation import generate_click
from ..train import train_clicks
from .common import add_shared_training_args


def add_click_parsers(subparsers: argparse._SubParsersAction) -> None:
    click_parser = subparsers.add_parser("train-clicks", help="Train the conditioned mouse click trajectory GRU.")
    add_shared_training_args(click_parser)
    click_parser.add_argument("--rest-ms", type=int, default=150)
    click_parser.add_argument("--max-duration-ms", type=int, default=2000)
    click_parser.add_argument("--min-distance", type=float, default=8.0)
    click_parser.add_argument("--dt-loss-weight", type=float, default=1.0)
    click_parser.add_argument("--pos-loss-weight", type=float, default=1.0)
    click_parser.add_argument("--click-action-weight", type=float, default=8.0)
    click_parser.add_argument("--click-duration-loss-weight", type=float, default=0.0)
    click_parser.add_argument("--wandb-click-rollout-examples", type=int, default=128, help="Validation click rollouts to chart in W&B after training. 0 disables this diagnostic.")
    click_parser.add_argument("--wandb-click-rollout-max-steps", type=int, default=80)
    click_parser.add_argument("--wandb-click-rollout-click-threshold", type=float, default=0.98)
    click_parser.add_argument("--wandb-click-rollout-min-dt-ms", type=float, default=4.0)
    click_parser.set_defaults(func=train_clicks)

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
