"""Helpers shared by the CLI command modules."""

import datetime as dt
from collections.abc import Callable

import orjson
import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from . import client
from .app import console


def emit_json(payload: object) -> None:
    """Write a compact JSON document to stdout."""
    typer.echo(orjson.dumps(payload).decode())


_SINCE_UNITS = {"m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def parse_timestamp(value: str) -> int:
    """Parse '7d', '24h', '2w', '30m', or an ISO date into epoch milliseconds."""
    text = value.strip().lower()
    if len(text) > 1 and text[-1] in _SINCE_UNITS and text[:-1].isdigit():
        seconds = int(text[:-1]) * _SINCE_UNITS[text[-1]]
        return int((dt.datetime.now() - dt.timedelta(seconds=seconds)).timestamp() * 1000)

    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise client.OpenCodeError(
            f"Invalid date value {value!r}; use 7d, 24h, 2w, or YYYY-MM-DD."
        ) from exc
    return int(moment.timestamp() * 1000)


def bulk_apply(
    session_ids: list[str],
    action: Callable[[str], None],
    *,
    label: str,
    progress_text: str,
) -> None:
    """Apply *action* to each id, with a progress bar on terminals and lines elsewhere."""
    total = len(session_ids)
    done = 0
    failure: tuple[str, str] | None = None

    def run_one(session_id: str) -> bool:
        nonlocal done, failure
        try:
            action(session_id)
        except client.OpenCodeError as exc:
            failure = (session_id, str(exc))
            return False
        done += 1
        return True

    interactive = console.is_terminal and total > 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[dim]{progress_text}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
        disable=not interactive,
    ) as progress:
        task = progress.add_task(progress_text, total=total)
        for session_id in session_ids:
            if not run_one(session_id):
                break
            if not interactive:
                console.print(f"[green]{label}[/] {session_id}")
            progress.advance(task)

    if failure is not None:
        failed_id, error = failure
        raise client.OpenCodeError(
            f"{label} {done} of {total} session(s); failed on {failed_id}: {error}"
        )

    if interactive:
        console.print(f"[green]{label}[/] {total} session(s).")


def delete_sessions(service: client.OpenCodeClient, session_ids: list[str]) -> None:
    """Delete sessions with progress feedback."""
    bulk_apply(session_ids, service.delete_session, label="Deleted", progress_text="deleting")
