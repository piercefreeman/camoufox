"""Click command for dataset inspection."""

from __future__ import annotations

import click

from ..train import inspect_recordings
from .common import CONTEXT_SETTINGS, namespace


@click.command("inspect", context_settings=CONTEXT_SETTINGS, help="Show event and training episode counts.")
@click.argument("inputs", nargs=-1)
@click.option("--rest-ms", type=int, default=150, show_default=True)
@click.option("--max-duration-ms", type=int, default=2000, show_default=True)
@click.option("--min-distance", type=float, default=8.0, show_default=True)
@click.option("--gap-ms", type=int, default=1000, show_default=True)
@click.option(
    "--keyboard-accessibility-id",
    default="auto",
    show_default=True,
    help="Focused text accessibility id to train from. 'auto' selects the most active single element identity.",
)
@click.option(
    "--keyboard-max-snapshot-edit-actions",
    type=int,
    default=12,
    show_default=True,
    help="Focused text value jumps larger than this start a new segment.",
)
def inspect_command(
    inputs: tuple[str, ...],
    rest_ms: int,
    max_duration_ms: int,
    min_distance: float,
    gap_ms: int,
    keyboard_accessibility_id: str,
    keyboard_max_snapshot_edit_actions: int,
) -> None:
    """Inspect capture files and print corpus counts as JSON."""
    inspect_recordings(
        namespace(
            inputs=list(inputs),
            rest_ms=rest_ms,
            max_duration_ms=max_duration_ms,
            min_distance=min_distance,
            gap_ms=gap_ms,
            keyboard_accessibility_id=keyboard_accessibility_id,
            keyboard_max_snapshot_edit_actions=keyboard_max_snapshot_edit_actions,
        )
    )
