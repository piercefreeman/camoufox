"""CLI wiring for dataset inspection."""

from __future__ import annotations

import argparse

from ..train import inspect_recordings


def add_inspect_parser(subparsers: argparse._SubParsersAction) -> None:
    inspect_parser = subparsers.add_parser("inspect", help="Show event and training episode counts.")
    inspect_parser.add_argument("inputs", nargs="*", help="Recording files or directories. Defaults to ./recordings.")
    inspect_parser.add_argument("--rest-ms", type=int, default=150)
    inspect_parser.add_argument("--max-duration-ms", type=int, default=2000)
    inspect_parser.add_argument("--min-distance", type=float, default=8.0)
    inspect_parser.add_argument("--gap-ms", type=int, default=1000)
    inspect_parser.add_argument("--synthetic-per-sequence", type=int, default=4)
    inspect_parser.add_argument("--geometry-tolerance", type=float, default=0.05)
    inspect_parser.add_argument("--include-repeats", action="store_true")
    inspect_parser.add_argument("--keyboard-text-source", choices=["auto", "focused", "synthetic"], default="auto")
    inspect_parser.add_argument("--keyboard-accessibility-id", default="auto", help="Focused text accessibility id to train from. 'auto' selects the most active single element identity.")
    inspect_parser.add_argument("--keyboard-max-snapshot-edit-actions", type=int, default=12, help="Focused text value jumps larger than this start a new segment.")
    inspect_parser.add_argument("--seed", type=int, default=13)
    inspect_parser.set_defaults(func=inspect_recordings)
