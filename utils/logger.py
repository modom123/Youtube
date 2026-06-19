"""Rich-powered logging for the Social Optimize Machine."""
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint
from contextlib import contextmanager

console = Console()


def header(text: str) -> None:
    console.print(Panel(f"[bold cyan]{text}[/bold cyan]", expand=False))


def step(icon: str, message: str) -> None:
    console.print(f"  {icon}  {message}")


def success(message: str) -> None:
    console.print(f"  [bold green]✓[/bold green]  {message}")


def warn(message: str) -> None:
    console.print(f"  [bold yellow]⚠[/bold yellow]  {message}")


def error(message: str) -> None:
    console.print(f"  [bold red]✗[/bold red]  {message}")


def info(message: str) -> None:
    console.print(f"  [dim]ℹ[/dim]  {message}")


@contextmanager
def spinner(message: str):
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[cyan]{message}[/cyan]"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        progress.add_task("", total=None)
        yield


def print_job_summary(manifest: dict) -> None:
    table = Table(title="Job Summary", show_header=True, header_style="bold magenta")
    table.add_column("Field", style="cyan", width=20)
    table.add_column("Value", style="white")

    table.add_row("Topic", manifest.get("topic", "-"))
    table.add_row("Content Type", manifest.get("content_type", "-"))
    table.add_row("Title", manifest.get("title", "-")[:60])
    table.add_row("Duration", f"{manifest.get('duration', 0):.0f}s")

    results = manifest.get("publish_results", {})
    for platform, result in results.items():
        if isinstance(result, dict):
            url = result.get("url", result.get("publish_id", "submitted"))
            table.add_row(f"  {platform.title()}", str(url))

    console.print(table)
