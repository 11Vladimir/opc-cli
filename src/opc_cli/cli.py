"""Command line entry point for opc."""

from typing import Annotated

import typer
from rich.console import Console

from . import __version__, client
from .app import app, console  # noqa: F401  (console is re-exported for tests)
from .commands import export as _export  # noqa: F401  (registers commands)
from .commands import sessions as _sessions  # noqa: F401
from .commands import stats as _stats  # noqa: F401
from .helpers import bulk_apply, emit_json, parse_timestamp  # noqa: F401


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"opc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "-V",
            "--version",
            help="Show the version and exit.",
            is_eager=True,
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """Manage OpenCode sessions from the terminal."""


def main() -> None:
    """Run the CLI, reporting service errors without a traceback."""
    try:
        app()
    except client.OpenCodeError as exc:
        Console(stderr=True).print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
