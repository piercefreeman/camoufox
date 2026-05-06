"""Shared CLI argument groups."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_shared_training_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="*", help="Recording files or directories. Defaults to ./recordings.")
    parser.add_argument("--output-dir", type=Path, default=Path("Training/runs"))
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden-size", type=int, default=96)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--device", default=None, help="cpu, cuda, or mps. Defaults to cuda when available, else cpu.")
    parser.add_argument("--early-stopping-patience", type=int, default=0, help="Stop after this many epochs without validation improvement. 0 disables early stopping.")
    parser.add_argument("--early-stopping-min-delta", type=float, default=0.0, help="Minimum validation-loss improvement required to reset early stopping.")
    parser.add_argument("--wandb", action=argparse.BooleanOptionalAction, default=False, help="Log config, metrics, summaries, and checkpoints to Weights & Biases.")
    parser.add_argument("--wandb-project", default=None, help="W&B project name. If omitted, W&B uses its configured default.")
    parser.add_argument("--wandb-entity", default=None, help="Optional W&B entity/team.")
    parser.add_argument("--wandb-run-name", default=None, help="Optional W&B run name.")
    parser.add_argument("--wandb-group", default=None, help="Optional W&B run group.")
    parser.add_argument("--wandb-tags", default="", help="Comma-separated W&B tags.")
    parser.add_argument("--wandb-mode", choices=["online", "offline", "disabled"], default=None, help="W&B mode. Use offline to log locally or disabled to suppress W&B.")
    parser.add_argument("--wandb-watch", action=argparse.BooleanOptionalAction, default=False, help="Ask W&B to watch model gradients.")
    parser.add_argument("--wandb-log-artifacts", action=argparse.BooleanOptionalAction, default=True, help="Upload model checkpoints and metrics.jsonl as a W&B artifact.")
