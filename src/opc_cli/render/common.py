"""Formatting primitives and shared Rich styling."""

import datetime as dt
import os
from pathlib import Path
from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

AGENT_STYLES: dict[str, str] = {
    "build": "cyan",
    "plan": "yellow",
    "mentor": "magenta",
    "general": "blue",
    "explore": "blue",
    "docs": "green",
}


def plural(count: int, word: str) -> str:
    """Return '1 session' / '2 sessions' style labels."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def format_tokens(count: int) -> str:
    """Compact token count, e.g. 12345 -> 12.3k."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def format_time(ms: int | None) -> str:
    """Convert an OpenCode millisecond timestamp to a local time string."""
    if not ms:
        return "-"
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def format_short_time(ms: int | None, now: dt.datetime | None = None) -> str:
    """Compact relative timestamp for tables (e.g. '5m ago', '3h ago')."""
    if not ms:
        return "-"
    moment = dt.datetime.fromtimestamp(ms / 1000)
    reference = now or dt.datetime.now()
    seconds = max(0, int((reference - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    if seconds < 86_400 * 30:
        return f"{seconds // 86_400}d ago"
    return moment.strftime("%Y-%m-%d")


def format_until(ms: int | None) -> str:
    """Format a future millisecond timestamp as a compact countdown."""
    if not ms:
        return "-"
    moment = dt.datetime.fromtimestamp(ms / 1000)
    seconds = max(0, int((moment - dt.datetime.now()).total_seconds()))
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"resets in {days}d {hours:02d}h"
    if hours > 0:
        return f"resets in {hours}h {minutes:02d}m"
    return f"resets in {minutes}m"


def kv_panel(rows: list[tuple[str, Any]], *, title: str, pad: int = 14) -> Panel:
    """Build a key-value panel from (label, value) pairs."""
    body = Text()
    for index, (label, value) in enumerate(rows):
        if index:
            body.append("\n")
        body.append(f"{label:<{pad}}", style="dim")
        body.append(str(value))
    return Panel(body, title=title, border_style="cyan", expand=False, padding=(1, 2))


def collapse_home(path: str) -> str:
    """Replace the home directory prefix with a tilde."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def model_label(model: dict[str, Any] | None) -> str:
    """Format a session model reference."""
    if not model:
        return "-"
    label = model.get("id", "?")
    provider = model.get("providerID")
    if provider:
        label = f"{provider}/{label}"
    variant = model.get("variant")
    if variant:
        label += f" ({variant})"
    return label


def short_id(session_id: str) -> str:
    """Shorten a session id to a copyable prefix."""
    return session_id if len(session_id) <= 13 else session_id[:13]


def format_id(session_id: str) -> str:
    """Style a shortened session id, dimming the static 'ses_' prefix."""
    short = short_id(session_id)
    if short.startswith("ses_"):
        return f"[dim]ses_[/][cyan]{short[4:]}[/]"
    return f"[cyan]{short}[/]"


def format_agent(agent: str | None) -> str:
    """Style an agent name by role."""
    if not agent:
        return "[dim]-[/]"
    style = AGENT_STYLES.get(agent, "white")
    return f"[{style}]{escape(agent)}[/]"


def format_styled_tokens(count: int) -> str:
    """Style token count by magnitude."""
    text = format_tokens(count)
    if count == 0:
        return f"[dim]{text}[/]"
    if count >= 1_000_000:
        return f"[yellow]{text}[/]"
    return text


def session_state(session: dict[str, Any]) -> str:
    """Return a running/archived/subagent marker, or a blank gutter for idle sessions."""
    time = session.get("time", {})
    if "busy" in time and "idle" not in time:
        return "[green]*[/]"
    if time.get("archived"):
        return "[dim]a[/]"
    if session.get("parentID"):
        return "[dim]↳[/]"
    return " "


def base_table(width: int = 120, *, caption: str | None = None) -> Table:
    """Create a table with the shared opc styling."""
    return Table(
        box=box.SIMPLE_HEAD,
        header_style="bold",
        border_style="dim",
        pad_edge=False,
        expand=True,
        width=min(width, 140),
        caption=caption,
        caption_style="dim",
        caption_justify="left",
    )


def is_current_directory(path: str, cwd: Path | None = None) -> bool:
    """Return True when *path* resolves to the current (or supplied) directory."""
    try:
        current = cwd if cwd is not None else Path.cwd().resolve()
        return Path(path).resolve() == current
    except OSError:
        return False


def format_directory(directory: str, cwd: Path | None = None) -> str:
    """Render a directory cell, highlighting the current working directory."""
    label = escape(collapse_home(directory))
    if directory != "-" and is_current_directory(directory, cwd):
        return f"[green]{label}[/]"
    return f"[dim]{label}[/]"
