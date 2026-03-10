"""Rich formatting helpers for Charon CLI output."""

import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress_bar import ProgressBar
from rich.theme import Theme

CHARON_THEME = Theme({
    "danger": "bold red",
    "warning": "bold yellow",
    "good": "bold green",
    "info": "bold cyan",
    "dim": "dim white",
    "header": "bold white",
})

# Force UTF-8 on Windows to avoid cp1252 encoding errors.
# Only wrap when running interactively (not under pytest or piped).
if sys.platform == "win32" and sys.stdout.isatty():
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(theme=CHARON_THEME)

BANNER = r"""
   _____ _    _          _____   ____  _   _
  / ____| |  | |   /\   |  __ \ / __ \| \ | |
 | |    | |__| |  /  \  | |__) | |  | |  \| |
 | |    |  __  | / /\ \ |  _  /| |  | | . ` |
 | |____| |  | |/ ____ \| | \ \| |__| | |\  |
  \_____|_|  |_/_/    \_\_|  \_\\____/|_| \_|

       Getting you to the other side.
"""


def print_banner() -> None:
    """Display the Charon ASCII banner."""
    console.print(BANNER, style="info")


def print_error(message: str) -> None:
    """Display an error message."""
    console.print(f"[danger][X][/danger] {message}")


def print_warning(message: str) -> None:
    """Display a warning message."""
    console.print(f"[warning][!][/warning] {message}")


def print_success(message: str) -> None:
    """Display a success message."""
    console.print(f"[good][+][/good] {message}")


def print_info(message: str) -> None:
    """Display an informational message."""
    console.print(f"[info][>][/info] {message}")


def print_score(label: str, score: float, max_score: float = 100.0) -> None:
    """Display a score with a colored progress bar (higher = worse)."""
    ratio = score / max_score
    if ratio >= 0.7:
        color = "red"
    elif ratio >= 0.4:
        color = "yellow"
    else:
        color = "green"

    bar_width = 30
    filled = int(ratio * bar_width)
    empty = bar_width - filled
    bar = f"[{color}]{'#' * filled}[/{color}][dim]{'.' * empty}[/dim]"

    console.print(f"  {label}: {bar} {score:.0f}/{max_score:.0f}")


def print_score_inverted(label: str, score: float, max_score: float = 100.0) -> None:
    """Display a score where higher is better (green high, red low)."""
    ratio = score / max_score
    if ratio >= 0.7:
        color = "green"
    elif ratio >= 0.4:
        color = "yellow"
    else:
        color = "red"

    bar_width = 30
    filled = int(ratio * bar_width)
    empty = bar_width - filled
    bar = f"[{color}]{'#' * filled}[/{color}][dim]{'.' * empty}[/dim]"

    console.print(f"  {label}: {bar} {score:.0f}/{max_score:.0f}")


def make_flag_table(title: str) -> Table:
    """Create a table for flag display."""
    table = Table(title=title, show_header=True, header_style="bold white", border_style="dim")
    table.add_column("Tier", style="bold", width=6)
    table.add_column("Flag", min_width=30)
    table.add_column("Details", min_width=40)
    return table


def panel(title: str, content: str, style: str = "info") -> None:
    """Display a bordered panel."""
    console.print(Panel(content, title=f"[{style}]{title}[/{style}]", border_style=style))


def section_header(title: str) -> None:
    """Display a section header."""
    console.print()
    console.print(f"[header]=== {title} ===[/header]")
    console.print()
