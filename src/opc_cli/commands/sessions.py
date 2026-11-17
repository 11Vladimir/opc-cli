"""Session lifecycle commands."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .. import client, render
from ..app import app, console
from ..helpers import bulk_apply, delete_sessions, emit_json


@app.command("ls")
def ls(
    directory: Annotated[
        str | None,
        typer.Option("-C", "--dir", help="Only sessions from this directory."),
    ] = None,
    search: Annotated[str | None, typer.Option("-s", "--search", help="Filter by title.")] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "-p", "--project", help="Only sessions of this project (id, prefix, or path)."
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Number of sessions.", min=1),
    ] = 30,
    order: Annotated[
        client.SortOrder,
        typer.Option("-o", "--order", help="Sort order (asc: oldest first, desc: newest first)."),
    ] = client.SortOrder.ASC,
    show_all: Annotated[bool, typer.Option("-a", "--all", help="Include archived.")] = False,
    roots_only: Annotated[
        bool,
        typer.Option("--roots", help="Only root sessions (exclude subagents)."),
    ] = False,
    count: Annotated[
        bool,
        typer.Option("--count", help="Count every session for an exact total (slower)."),
    ] = False,
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Print raw JSON.")] = False,
) -> None:
    """List sessions."""

    with client.OpenCodeClient.connect() as service:
        project_id = service.resolve_project(project) if project else None

        if count:
            all_sessions = service.list_all_sessions(
                directory=directory,
                search=search,
                project=project_id,
                roots_only=roots_only,
                order=order,
                include_archived=show_all,
            )
            sessions = all_sessions[:limit]
            total: int | None = len(all_sessions)
            has_more = total > len(sessions)
        else:
            page, has_more = service.list_sessions_page(
                directory=directory,
                search=search,
                project=project_id,
                roots_only=roots_only,
                limit=max(limit, client.PAGE_SIZE),
                order=order,
                include_archived=show_all,
            )
            sessions = page[:limit]
            total = None if has_more else len(page)

    if as_json:
        payload = {"total": total, "has_more": has_more, "sessions": sessions}
        emit_json(payload)
        return

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    console.print(
        render.sessions_table(sessions, width=console.width, total=total, has_more=has_more)
    )
    legend = render.legend(sessions)
    if legend is not None:
        console.print(legend)


@app.command("show", no_args_is_help=True)
def show(
    session: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    messages: Annotated[
        int,
        typer.Option("-m", "--messages", help="Messages to show.", min=1),
    ] = 6,
    as_json: Annotated[bool, typer.Option("-j", "--json", help="Print raw JSON.")] = False,
) -> None:
    """Show a session and its latest messages."""
    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        details = service.get_session(session_id)
        data = service.get_messages(session_id, limit=messages)

    if as_json:
        emit_json({"session": details, "messages": data})
        return

    console.print(render.session_panel(details))
    if data:
        console.print(render.message_panels(data))


def _describe_sessions(session_ids: list[str], limit: int = 5) -> str:
    """Join session ids for a prompt, truncating long batches."""
    shown = ", ".join(session_ids[:limit])
    if len(session_ids) > limit:
        shown += ", …"
    return shown


@app.command("rm", no_args_is_help=True)
def rm(
    sessions: Annotated[
        list[str],
        typer.Argument(help="Session id(s) or unique prefix(es)."),
    ],
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")] = False,
) -> None:
    """Delete one or more sessions."""
    with client.OpenCodeClient.connect() as service:
        session_ids = service.resolve_sessions(sessions)
        prompt = f"Delete {len(session_ids)} session(s): {_describe_sessions(session_ids)}?"

        if not yes and not typer.confirm(prompt):
            raise typer.Abort()

        delete_sessions(service, session_ids)


@app.command("clean")
def clean(
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List the sessions and exit without deleting."),
    ] = False,
) -> None:
    """Delete all empty untitled sessions."""
    with client.OpenCodeClient.connect() as service:
        empty = service.list_empty_sessions()

        if not empty:
            console.print("[dim]No empty sessions found.[/]")
            return

        console.print(render.sessions_table(empty, width=console.width))
        legend = render.legend(empty)
        if legend is not None:
            console.print(legend)
        if dry_run:
            console.print(f"[dim]Dry run: {len(empty)} empty session(s) would be deleted.[/]")
            return

        if not yes and not typer.confirm(f"Delete {len(empty)} empty session(s)?"):
            raise typer.Abort()

        delete_sessions(service, [session["id"] for session in empty])


@app.command("resume", no_args_is_help=True)
def resume(
    session: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    print_only: Annotated[
        bool,
        typer.Option("-p", "--print", help="Print the command instead of running it."),
    ] = False,
    tmux: Annotated[
        bool,
        typer.Option("-t", "--tmux", help="Open the session in a new tmux window."),
    ] = False,
) -> None:
    """Resume a session in OpenCode within its original working directory."""
    if print_only and tmux:
        raise client.OpenCodeError("Use either --print or --tmux, not both.")

    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        details = service.get_session(session_id)

    binary = shutil.which("opencode")
    if not binary:
        raise client.OpenCodeError("`opencode` binary was not found on PATH.")

    directory = details.get("location", {}).get("directory")
    target = Path(directory) if directory else None

    invoke = f"{shlex.quote(binary)} -s {shlex.quote(session_id)}"
    if print_only:
        typer.echo(f"cd {shlex.quote(str(target))} && {invoke}" if target else invoke)
        return

    workdir = target if target and target.is_dir() else Path.cwd()
    if target and not target.is_dir():
        Console(stderr=True).print(
            f"[yellow]Directory {directory} does not exist; using current directory.[/]"
        )

    if tmux:
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise client.OpenCodeError("`tmux` binary was not found on PATH.")
        pane = "new-window" if os.environ.get("TMUX") else "new-session"
        completed = subprocess.run(
            [tmux_bin, pane, "-c", str(workdir), "--", binary, "-s", session_id],
            check=False,
        )
        if completed.returncode != 0:
            raise client.OpenCodeError(f"tmux exited with code {completed.returncode}")
        return

    if target and target.is_dir():
        os.chdir(target)

    os.execvp(binary, [binary, "-s", session_id])


@app.command("fork", no_args_is_help=True)
def fork(
    session: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    before: Annotated[
        str | None,
        typer.Option("-b", "--before", help="Fork before this message id."),
    ] = None,
) -> None:
    """Fork a session into a new one."""
    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        created = service.fork_session(session_id, before=before)

    console.print(render.session_panel(created))


def _set_archived(sessions: list[str], *, archived: bool) -> None:
    """Archive or restore several sessions with progress feedback."""
    label = "Archived" if archived else "Restored"
    progress_text = "archiving" if archived else "restoring"
    with client.OpenCodeClient.connect() as service:
        session_ids = service.resolve_sessions(sessions)
        bulk_apply(
            session_ids,
            lambda session_id: service.set_archived(session_id, archived=archived),
            label=label,
            progress_text=progress_text,
        )


@app.command("archive", no_args_is_help=True)
def archive(
    sessions: Annotated[
        list[str],
        typer.Argument(help="Session id(s) or unique prefix(es)."),
    ],
) -> None:
    """Archive one or more sessions."""
    _set_archived(sessions, archived=True)


@app.command("unarchive", no_args_is_help=True)
def unarchive(
    sessions: Annotated[
        list[str],
        typer.Argument(help="Session id(s) or unique prefix(es)."),
    ],
) -> None:
    """Restore archived sessions."""
    _set_archived(sessions, archived=False)


@app.command("rename", no_args_is_help=True)
def rename(
    session: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    title: Annotated[str, typer.Argument(help="New session title.")],
) -> None:
    """Rename a session."""
    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        service.rename_session(session_id, title)

    console.print(f"[green]Renamed[/] {session_id} -> {title}")


@app.command("mv", no_args_is_help=True)
def mv(
    session: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    directory: Annotated[str, typer.Argument(help="Destination directory.")],
) -> None:
    """Move a session to another directory."""
    target = Path(directory).expanduser().resolve()
    if not target.is_dir():
        raise client.OpenCodeError(f"Directory does not exist: {target}")

    with client.OpenCodeClient.connect() as service:
        session_id = service.resolve_session(session)
        service.move_session(session_id, target)

    console.print(f"[green]Moved[/] {session_id} -> {target}")
