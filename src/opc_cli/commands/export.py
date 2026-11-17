"""Session export commands."""

from pathlib import Path
from typing import Annotated

import orjson
import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from .. import client, render
from ..app import app, console
from ..helpers import parse_timestamp


def _export_all(
    target: Path,
    *,
    as_json: bool,
    sanitize: bool,
    directory: str | None,
    project: str | None,
    search: str | None,
    include_archived: bool,
    since: int | None = None,
) -> None:
    """Export every matching root session into *target*."""
    suffix = "json" if as_json else "md"

    with client.OpenCodeClient.connect() as service:
        project_id = service.resolve_project(project) if project else None
        sessions = [
            session
            for session in service.list_all_sessions(
                directory=directory,
                search=search,
                project=project_id,
                roots_only=True,
                include_archived=include_archived,
            )
            if not session.get("parentID")
            and (since is None or session.get("time", {}).get("updated", 0) >= since)
        ]
        if not sessions:
            console.print("[dim]No sessions to export.[/]")
            return

        target.mkdir(parents=True, exist_ok=True)
        total = len(sessions)
        interactive = console.is_terminal and total > 1

        with Progress(
            SpinnerColumn(),
            TextColumn("[dim]exporting"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
            disable=not interactive,
        ) as progress:
            task = progress.add_task("export", total=total)
            for session in sessions:
                session_id = session["id"]
                transfer = service.export_session(session_id, sanitize=sanitize)
                text = (
                    orjson.dumps(transfer).decode()
                    if as_json
                    else render.session_markdown(transfer)
                )
                (target / f"{session_id}.{suffix}").write_text(text, encoding="utf-8")
                progress.advance(task)

    console.print(f"[green]Exported[/] {total} session(s) -> {target}")


@app.command("export", no_args_is_help=True)
def export(
    session: Annotated[
        str | None,
        typer.Argument(help="Session id or unique prefix."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="File to write, or a directory with --all."),
    ] = None,
    all_sessions: Annotated[
        bool,
        typer.Option("--all", help="Export every root session into the --output directory."),
    ] = False,
    directory: Annotated[
        str | None,
        typer.Option("-C", "--dir", help="With --all: only sessions from this directory."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="With --all: only sessions of this project."),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("-s", "--search", help="With --all: filter by title."),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", help="With --all: only sessions updated since 7d/24h/ISO date."),
    ] = None,
    include_archived: Annotated[
        bool,
        typer.Option("--include-archived", help="With --all: include archived sessions."),
    ] = False,
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Export raw JSON.")] = False,
    sanitize: Annotated[
        bool,
        typer.Option("--sanitize", help="Redact secrets before exporting."),
    ] = False,
) -> None:
    """Export a session as Markdown or raw JSON."""
    if all_sessions:
        if output is None:
            raise client.OpenCodeError("--all requires --output <directory>.")
        if session is not None:
            raise client.OpenCodeError("Pass either a session id or --all, not both.")
        _export_all(
            output,
            as_json=as_json,
            sanitize=sanitize,
            directory=directory,
            project=project,
            search=search,
            include_archived=include_archived,
            since=parse_timestamp(since) if since else None,
        )
        return

    if session is None:
        raise client.OpenCodeError(
            "Missing session id. Use `opc export <session>` or `opc export --all -o DIR`."
        )

    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        transfer = service.export_session(session_id, sanitize=sanitize)

    text = orjson.dumps(transfer).decode() if as_json else render.session_markdown(transfer)

    if output:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]Exported[/] {session_id} -> {output}")
    else:
        typer.echo(text.rstrip("\n"))
