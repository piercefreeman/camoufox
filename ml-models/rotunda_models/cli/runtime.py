"""Click command for runtime model export."""

from __future__ import annotations

import json

import click

from ..runtime_export import export_runtime_checkpoint
from .common import CONTEXT_SETTINGS, PATH_TYPE


@click.command(
    "export-runtime",
    context_settings=CONTEXT_SETTINGS,
    help="Export checkpoints for native runtime decoding.",
)
@click.option("--mouse-checkpoint", type=PATH_TYPE, default=None)
@click.option("--keyboard-checkpoint", type=PATH_TYPE, default=None)
@click.option("--output-dir", type=PATH_TYPE, required=True)
@click.option("--mouse-output", default="mouse.safetensors", show_default=True)
@click.option("--keyboard-output", default="keyboard.safetensors", show_default=True)
@click.option("--device", default=None)
def export_runtime_command(
    mouse_checkpoint,
    keyboard_checkpoint,
    output_dir,
    mouse_output: str,
    keyboard_output: str,
    device: str | None,
) -> None:
    """Export selected checkpoints into native runtime artifacts."""
    outputs = []
    if mouse_checkpoint is None and keyboard_checkpoint is None:
        raise click.ClickException("Specify at least one of --mouse-checkpoint or --keyboard-checkpoint.")

    if mouse_checkpoint is not None:
        outputs.append(
            export_runtime_checkpoint(
                checkpoint_path=mouse_checkpoint,
                output_path=output_dir / mouse_output,
                device=device,
            )
        )
    if keyboard_checkpoint is not None:
        outputs.append(
            export_runtime_checkpoint(
                checkpoint_path=keyboard_checkpoint,
                output_path=output_dir / keyboard_output,
                device=device,
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
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "runtime-models.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(json.dumps({"manifest": str(manifest_path), "artifacts": outputs}, indent=2, sort_keys=True))
