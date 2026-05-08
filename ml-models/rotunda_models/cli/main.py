"""Top-level CLI for rotunda_models."""

from __future__ import annotations

import click

from ..train import train_experiment
from .clicks import generate_click_command
from .common import CONTEXT_SETTINGS, PATH_TYPE, namespace
from .inspect import inspect_command
from .keyboard import generate_keyboard_command
from .runtime import export_runtime_command


@click.group(
    context_settings=CONTEXT_SETTINGS,
    help="Train and inspect Rotunda cadence models from recorder NDJSON files.",
)
def cli() -> None:
    """Train and inspect Rotunda cadence models from recorder NDJSON files."""


@cli.command("train", context_settings=CONTEXT_SETTINGS, help="Run a YAML-defined training experiment.")
@click.argument("config", type=PATH_TYPE)
def train_command(config) -> None:
    """Run the task or tasks declared by a YAML experiment config."""
    train_experiment(namespace(config=config))


cli.add_command(inspect_command)
cli.add_command(generate_click_command)
cli.add_command(generate_keyboard_command)
cli.add_command(export_runtime_command)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the Click command tree."""
    try:
        cli.main(args=argv, prog_name="rotunda-models", standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
