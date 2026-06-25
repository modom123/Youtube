#!/usr/bin/env python3
"""
Social Optimize - CLI
Usage: python main.py create "your topic here" [options]
"""
import sys
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
def cli():
    """Social Optimize - Turn any topic into viral content."""
    pass


@cli.command()
@click.argument("topic")
@click.option(
    "--format", "-f",
    type=click.Choice(["short", "long", "podcast", "reel"]),
    default="short",
    show_default=True,
    help="Content format to produce",
)
@click.option(
    "--platforms", "-p",
    multiple=True,
    type=click.Choice(["youtube", "tiktok", "instagram"]),
    help="Platforms to publish to (can repeat: -p youtube -p tiktok)",
)
@click.option(
    "--audience", "-a",
    default="general public",
    show_default=True,
    help="Target audience description",
)
@click.option(
    "--voice", "-v",
    default=None,
    help="TTS voice name (e.g. en-US-GuyNeural)",
)
@click.option(
    "--style", "-s",
    type=click.Choice(["fire", "ocean", "purple", "dark", "green", "sunset"]),
    default="fire",
    show_default=True,
    help="Thumbnail color style",
)
@click.option(
    "--privacy",
    type=click.Choice(["private", "unlisted", "public"]),
    default="private",
    show_default=True,
    help="Upload privacy level",
)
@click.option("--instructions", "-i", default=None, help="Extra AI instructions")
@click.option("--dry-run", is_flag=True, help="Generate content but skip uploading")
@click.option("--cleanup", is_flag=True, help="Delete stock media files after completion")
def create(topic, format, platforms, audience, voice, style, privacy, instructions, dry_run, cleanup):
    """
    Create a complete content package from a TOPIC.

    Examples:\n
      python main.py create "The Future of AI" --format long -p youtube\n
      python main.py create "Morning routine tips" -f short -p tiktok -p youtube\n
      python main.py create "Tech Startup Stories" -f podcast -p youtube --privacy unlisted\n
      python main.py create "5 Python tricks" -f reel -p instagram --dry-run
    """
    import social_optimize

    console.print(Panel(
        f"[bold cyan]Social Optimize[/bold cyan]\n"
        f"[dim]Creating [bold]{format}[/bold] content about: [bold yellow]{topic}[/bold yellow][/dim]",
        expand=False,
    ))

    try:
        manifest = social_optimize.run(
            topic=topic,
            format=format,
            platforms=list(platforms),
            audience=audience,
            voice=voice,
            thumbnail_style=style,
            privacy=privacy,
            custom_instructions=instructions,
            dry_run=dry_run,
            cleanup=cleanup,
        )
        console.print(f"\n[bold green]Output directory:[/bold green] {manifest['job_dir']}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument("topic")
@click.option("--platforms", "-p", multiple=True, default=["youtube", "tiktok", "instagram"])
@click.option("--audience", "-a", default="general public")
@click.option("--dry-run", is_flag=True)
def blitz(topic, platforms, audience, dry_run):
    """
    BLITZ mode: Create ALL formats (short + long + reel) and publish everywhere at once.

    Example: python main.py blitz "Healthy eating on a budget" -p youtube -p tiktok
    """
    import social_optimize

    console.print(Panel(
        f"[bold red]BLITZ MODE[/bold red]\n"
        f"Creating ALL formats for: [bold yellow]{topic}[/bold yellow]",
        expand=False,
    ))

    formats = ["short", "long", "podcast"]
    results = {}

    for fmt in formats:
        console.rule(f"[cyan]{fmt.upper()}[/cyan]")
        try:
            manifest = social_optimize.run(
                topic=topic,
                format=fmt,
                platforms=list(platforms),
                audience=audience,
                dry_run=dry_run,
            )
            results[fmt] = manifest
        except Exception as e:
            console.print(f"[red]{fmt} failed: {e}[/red]")
            results[fmt] = {"error": str(e)}

    console.rule("[bold green]BLITZ COMPLETE[/bold green]")
    _print_blitz_summary(topic, results)


def _print_blitz_summary(topic: str, results: dict) -> None:
    table = Table(title=f"Blitz Results: {topic[:40]}", show_header=True)
    table.add_column("Format", style="cyan")
    table.add_column("Status")
    table.add_column("File")
    table.add_column("Published")

    for fmt, manifest in results.items():
        if "error" in manifest:
            table.add_row(fmt, "[red]FAILED[/red]", manifest["error"][:40], "")
        else:
            video = manifest.get("files", {}).get("video", "")
            pubs = manifest.get("publish_results", {})
            pub_str = ", ".join(pubs.keys()) if pubs else "not published"
            table.add_row(fmt, "[green]OK[/green]", video[-40:] if video else "-", pub_str)

    console.print(table)


@cli.command()
def jobs():
    """List all past content generation jobs."""
    from utils import file_manager
    all_jobs = file_manager.list_jobs()
    if not all_jobs:
        console.print("[dim]No jobs found in output directory.[/dim]")
        return

    table = Table(title="Past Jobs", show_header=True)
    table.add_column("Date", style="dim")
    table.add_column("Topic", style="cyan")
    table.add_column("Format")
    table.add_column("Duration")
    table.add_column("Published")

    for job in all_jobs[:20]:
        date = job.get("created_at", "?")[:16].replace("T", " ")
        topic = job.get("topic", "?")[:35]
        fmt = job.get("format", "?")
        dur = f"{job.get('duration', 0):.0f}s"
        pubs = ", ".join(job.get("publish_results", {}).keys()) or "-"
        table.add_row(date, topic, fmt, dur, pubs)

    console.print(table)


@cli.command()
def voices():
    """List all available TTS voices."""
    from generators import audio_generator
    with console.status("Fetching voices..."):
        vs = audio_generator.list_voices_sync()

    table = Table(title="Available Voices (English)", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Locale")
    table.add_column("Gender")

    for v in vs:
        table.add_row(v["ShortName"], v["Locale"], v["Gender"])

    console.print(table)
    console.print(f"\nTotal: {len(vs)} English voices")
    console.print("Use with: [cyan]--voice en-US-GuyNeural[/cyan]")


@cli.command()
def setup():
    """Check configuration and API key status."""
    import config

    console.print(Panel("[bold]Configuration Check[/bold]", expand=False))

    checks = [
        ("ANTHROPIC_API_KEY", bool(config.ANTHROPIC_API_KEY), "Required for script generation"),
        ("PEXELS_API_KEY", bool(config.PEXELS_API_KEY), "Required for stock media (optional)"),
        ("YOUTUBE_CLIENT_ID", bool(config.YOUTUBE_CLIENT_ID), "Required for YouTube uploads"),
        ("TIKTOK_ACCESS_TOKEN", bool(config.TIKTOK_ACCESS_TOKEN), "Required for TikTok uploads"),
        ("INSTAGRAM_ACCESS_TOKEN", bool(config.INSTAGRAM_ACCESS_TOKEN), "Required for Instagram uploads"),
    ]

    table = Table(show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Status")
    table.add_column("Notes", style="dim")

    for name, ok, notes in checks:
        status = "[green]✓ Set[/green]" if ok else "[red]✗ Missing[/red]"
        table.add_row(name, status, notes)

    console.print(table)
    console.print("\nCopy [cyan].env.example[/cyan] to [cyan].env[/cyan] and fill in your API keys.")


if __name__ == "__main__":
    cli()
