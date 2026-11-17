"""Usage, quota, and per-model tables."""

from typing import Any

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .common import (
    base_table,
    format_styled_tokens,
    format_tokens,
    format_until,
    kv_panel,
    model_label,
)


def stats_panel(data: dict[str, Any], *, context: str | None = None) -> Panel:
    """Build the aggregate usage panel."""
    tokens = data.get("tokens", {})
    tools = data.get("tools", {}).get("totals", {})
    rows = [
        ("sessions", data.get("sessions", 0)),
        ("subagents", data.get("subagents", 0)),
        ("prompts", data.get("prompts", 0)),
        ("steps", data.get("steps", 0)),
        ("input tokens", format_tokens(tokens.get("input", 0))),
        ("output tokens", format_tokens(tokens.get("output", 0))),
        ("tool calls", tools.get("calls", 0)),
        ("tool failures", tools.get("failed", 0)),
        ("active days", data.get("activeDays", 0)),
        ("streak", data.get("streak", 0)),
        ("cost", f"${data.get('cost', 0):.4f}"),
    ]

    title = f"usage · {context}" if context else "usage"
    return kv_panel(rows, title=title, pad=14)


def limits_panel(data: dict[str, Any], bar_width: int = 22) -> Panel:
    """Build the quota and budget limits panel."""
    workspace = data.get("workspace", {})
    ws_name = workspace.get("name")
    title = f"limits ({ws_name})" if ws_name else "limits"

    body = Text()
    go = data.get("go") or {}
    for label in ("rolling", "weekly", "monthly"):
        meter = go.get(label)
        if not isinstance(meter, dict):
            continue
        if body.plain:
            body.append("\n\n")
        pct = max(0.0, min(100.0, float(meter.get("percent", 0))))
        limited = bool(meter.get("limited"))
        filled = round(pct / 100 * bar_width)
        color = "red" if (limited or pct >= 85) else "yellow" if pct >= 60 else "green"

        body.append(f"{label:<11}", style="dim")
        body.append("━" * filled, style=color)
        body.append("─" * (bar_width - filled), style="dim")
        body.append(f"  {pct:3.0f}%", style=f"bold {color}" if limited else color)
        body.append(f"   {format_until(meter.get('resetsAt'))}", style="dim")

    for budget in data.get("budgets") or []:
        if body.plain:
            body.append("\n\n")
        limit = float(budget.get("limit", 0))
        spent = float(budget.get("spent", 0))
        body.append(f"{'budget':<11}", style="dim")
        body.append(f"${spent:.2f} / ${limit:.2f}")
        body.append(f"   {format_until(budget.get('resetsAt'))}", style="dim")

    if not body.plain:
        body.append("No active limits.", style="dim")

    usage_url = workspace.get("usageURL")
    if isinstance(usage_url, str) and usage_url:
        body.append("\n\n")
        body.append("console  ", style="dim")
        body.append(usage_url, style="dim")

    return Panel(body, title=title, border_style="cyan", expand=False, padding=(1, 2))


def models_table(models: list[dict[str, Any]], width: int = 120) -> Table:
    """Build a per-model token and step breakdown table."""
    table = base_table(width)
    table.add_column("model", no_wrap=True, overflow="ellipsis", ratio=3)
    table.add_column("steps", justify="right", no_wrap=True, width=7)
    table.add_column("input", justify="right", no_wrap=True, width=9)
    table.add_column("output", justify="right", no_wrap=True, width=9)
    table.add_column("reasoning", justify="right", no_wrap=True, width=10)
    table.add_column("cache read", style="dim", justify="right", no_wrap=True, width=11)

    ordered = sorted(
        models,
        key=lambda item: (
            item.get("tokens", {}).get("input", 0) + item.get("tokens", {}).get("output", 0),
            item.get("steps", 0),
        ),
        reverse=True,
    )

    for entry in ordered:
        tok = entry.get("tokens", {})
        cache = tok.get("cache", {})
        table.add_row(
            escape(model_label(entry.get("model"))),
            str(entry.get("steps", 0)),
            format_styled_tokens(tok.get("input", 0)),
            format_styled_tokens(tok.get("output", 0)),
            format_styled_tokens(tok.get("reasoning", 0)),
            format_tokens(cache.get("read", 0)),
        )

    return table
