"""CLI wiring for mouse click cadence commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..generation import generate_click


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
