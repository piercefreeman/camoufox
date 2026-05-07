"""Top-level CLI for rotunda_models."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..train import train_experiment
from .clicks import add_click_parsers
from .inspect import add_inspect_parser
from .keyboard import add_keyboard_parsers
from .runtime import add_runtime_parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and inspect Rotunda cadence models from recorder NDJSON files.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    train_parser = subparsers.add_parser("train", help="Run a YAML-defined training experiment.")
    train_parser.add_argument("config", type=Path, help="Path to a config/*.yml experiment file.")
    train_parser.set_defaults(func=train_experiment)
    add_inspect_parser(subparsers)
    add_click_parsers(subparsers)
    add_keyboard_parsers(subparsers)
    add_runtime_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the selected command handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
