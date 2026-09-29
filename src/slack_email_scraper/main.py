from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import Settings


def _load_settings(
    env_file: Path | None,
    *,
    targets_file: Path | None = None,
) -> Settings:
    try:
        return Settings.from_env(
            env_file,
            require_channels=False,
            targets_file=targets_file,
        )
    except ValueError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Scrape emails from Slack Directories (People profiles)."""


@cli.command("ui")
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--targets",
    "targets_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
def ui_cmd(
    env_file: Path | None,
    targets_file: Path | None,
    host: str,
    port: int,
) -> None:
    """Start UI. Open http://127.0.0.1:8765 in your Google Chrome."""
    _load_settings(env_file, targets_file=targets_file)
    from .ui_app import run_ui

    try:
        run_ui(host=host, port=port, env_file=env_file, targets_file=targets_file)
    except Exception as exc:
        click.echo(f"UI failed: {exc}", err=True)
        sys.exit(1)


main = cli

if __name__ == "__main__":
    cli()
