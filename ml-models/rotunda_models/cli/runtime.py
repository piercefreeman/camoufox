"""CLI wiring for runtime model export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..runtime_export import export_runtime_checkpoint


def export_runtime(args: argparse.Namespace) -> None:
    """Export selected checkpoints into native runtime artifacts."""
    outputs = []
    if args.mouse_checkpoint is None and args.keyboard_checkpoint is None:
        raise SystemExit("Specify at least one of --mouse-checkpoint or --keyboard-checkpoint.")

    if args.mouse_checkpoint is not None:
        outputs.append(
            export_runtime_checkpoint(
                checkpoint_path=args.mouse_checkpoint,
                output_path=args.output_dir / args.mouse_output,
                device=args.device,
            )
        )
    if args.keyboard_checkpoint is not None:
        outputs.append(
            export_runtime_checkpoint(
                checkpoint_path=args.keyboard_checkpoint,
                output_path=args.output_dir / args.keyboard_output,
                device=args.device,
            )
        )

    manifest = {
        "format": "rotunda-runtime-manifest-v1",
        "artifacts": [
            {
                "kind": output["kind"],
                "path": output["path"],
                "tensorCount": output["tensorCount"],
            }
            for output in outputs
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "runtime-models.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "artifacts": outputs}, indent=2, sort_keys=True))


def add_runtime_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register runtime export commands."""
    parser = subparsers.add_parser("export-runtime", help="Export checkpoints for native runtime decoding.")
    parser.add_argument("--mouse-checkpoint", type=Path, default=None)
    parser.add_argument("--keyboard-checkpoint", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mouse-output", default="mouse.safetensors")
    parser.add_argument("--keyboard-output", default="keyboard.safetensors")
    parser.add_argument("--device", default=None)
    parser.set_defaults(func=export_runtime)
