"""Shared CLI plumbing: the Typer app and the Rich console."""

import typer
from rich.console import Console

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Manage OpenCode sessions from the terminal.",
)
console = Console()
