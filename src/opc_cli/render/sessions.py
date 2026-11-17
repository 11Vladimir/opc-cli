"""Session and project tables."""

import datetime as dt
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .common import (
    base_table,
    format_agent,
    format_directory,
    format_id,
    format_short_time,
    format_styled_tokens,
    format_time,
    format_tokens,
    kv_panel,
    model_label,
    plural,
    session_state,
)


def legend(sessions: list[dict[str, Any]]) -> Text | None:
    """Build a dim legend line for the markers present in *sessions*."""
    entries: list[tuple[str, str, str]] = []

    def is_running(session: dict[str, Any]) -> bool:
        time = session.get("time", {})
        return "busy" in time and "idle" not in time

    if any(is_running(session) for session in sessions):
        entries.append(("*", "green", "running"))
    if any(session.get("parentID") for session in sessions):
        entries.append(("↳", "dim", "subagent"))
    if any(session.get("time", {}).get("archived") for session in sessions):
        entries.append(("a", "dim", "archived"))

    if not entries:
        return None

    line = Text()
    for index, (mark, style, label) in enumerate(entries):
        if index:
            line.append("   ", style="dim")
        line.append(mark, style=style)
        line.append(f" {label}", style="dim")
    return line


def sessions_table(
    sessions: list[dict[str, Any]],
    width: int = 120,
    total: int | None = None,
    has_more: bool = False,
) -> Table:
    """Build a responsive session list table."""
    show_agent = width >= 80
    show_directory = width >= 100
    extra = (total - len(sessions)) if total is not None and total > len(sessions) else 0
    count_label = plural(len(sessions), "session")
    if extra > 0:
        count_label += f" (+{extra} more)"
    elif has_more:
        count_label += " (+more)"

    table = base_table(width, caption=count_label)
    table.add_column("id", no_wrap=True, width=13)
    table.add_column("  title", no_wrap=True, overflow="ellipsis", ratio=3)
    if show_agent:
        table.add_column("agent", no_wrap=True, width=8)

    table.add_column("updated", style="dim", no_wrap=True, width=12)
    table.add_column("tokens", justify="right", no_wrap=True, width=8)

    if show_directory:
        table.add_column("directory", no_wrap=True, overflow="ellipsis", ratio=2)

    now = dt.datetime.now()
    cwd: Path | None = None
    if show_directory:
        try:
            cwd = Path.cwd().resolve()
        except OSError:
            cwd = None

    for session in sessions:
        time = session.get("time", {})
        tokens = session.get("tokens", {})
        total_tokens = tokens.get("input", 0) + tokens.get("output", 0)
        raw_title = escape(session["title"]) if session.get("title") else "<untitled>"
        is_subagent = bool(session.get("parentID"))
        title = f"[dim]{raw_title}[/]" if (is_subagent or not session.get("title")) else raw_title
        row = [format_id(session["id"]), f"{session_state(session)} {title}"]

        if show_agent:
            row.append(format_agent(session.get("agent")))

        row.append(format_short_time(time.get("updated"), now=now))
        row.append(format_styled_tokens(total_tokens))

        if show_directory:
            directory = session.get("location", {}).get("directory") or "-"
            row.append(format_directory(directory, cwd))
        table.add_row(*row)

    return table


def session_panel(session: dict[str, Any]) -> Panel:
    """Build the single-session details panel."""
    time = session.get("time", {})
    tokens = session.get("tokens", {})
    total = tokens.get("input", 0) + tokens.get("output", 0)
    rows = [
        ("id", session["id"]),
        ("title", session.get("title") or "<untitled>"),
        ("agent", session.get("agent") or "-"),
        ("model", model_label(session.get("model"))),
        ("directory", session.get("location", {}).get("directory") or "-"),
        ("updated", format_time(time.get("updated"))),
        (
            "tokens",
            f"{format_tokens(total)} total "
            f"({format_tokens(tokens.get('input', 0))} in / "
            f"{format_tokens(tokens.get('output', 0))} out)",
        ),
        ("cost", f"${session.get('cost', 0):.4f}"),
    ]

    return kv_panel(rows, title="session", pad=10)


def projects_table(
    projects: list[dict[str, Any]],
    counts: dict[str, int] | None = None,
    width: int = 120,
) -> Table:
    """Build the project list table."""
    table = base_table(width, caption=plural(len(projects), "project"))
    table.add_column("id", style="dim", no_wrap=True, width=10)
    table.add_column("path", overflow="ellipsis", ratio=3)
    if counts is not None:
        table.add_column("sessions", justify="right", no_wrap=True, width=8)
    table.add_column("active", style="dim", no_wrap=True, width=12)

    now = dt.datetime.now()
    try:
        cwd: Path | None = Path.cwd().resolve()
    except OSError:
        cwd = None
    ordered = sorted(
        projects,
        key=lambda project: project.get("time", {}).get("active", 0),
        reverse=True,
    )

    for project in ordered:
        project_id = str(project.get("id", ""))
        canonical = project.get("canonical") or "-"
        row = [project_id[:10], format_directory(canonical, cwd)]
        if counts is not None:
            row.append(str(counts.get(project_id, 0)))
        row.append(format_short_time(project.get("time", {}).get("active"), now=now))
        table.add_row(*row)

    return table
