"""Top-level CLI for rotunda_models."""

from __future__ import annotations

import argparse

from .clicks import add_click_parsers
from .inspect import add_inspect_parser
from .keyboard import add_keyboard_parsers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and inspect Rotunda cadence models from recorder NDJSON files.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_inspect_parser(subparsers)
    add_click_parsers(subparsers)
    add_keyboard_parsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
