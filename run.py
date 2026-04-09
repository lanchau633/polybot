#!/usr/bin/env python3
"""
run.py — PolyBot entry point.

Starts the V2 async pipeline with all Phase 1-3 modules wired in.
Used by systemd (polybot.service) and for local development.

Usage:
  python run.py              # default: dry-run mode
  DRY_RUN=false python run.py  # live mode (Phase 5 only!)
"""
from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.panel import Panel

import config

console = Console()


def setup_logging() -> None:
    """Configure structured logging for both console and journald."""
    level = logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def print_banner() -> None:
    mode = "[red bold]LIVE[/red bold]" if not config.DRY_RUN else "[yellow]DRY RUN[/yellow]"
    console.print(Panel(
        f"[bold bright_green]PolyBot[/bold bright_green] starting  |  Mode: {mode}\n"
        f"  Scanner interval: {config.SPORTS_SCAN_INTERVAL}s\n"
        f"  Edge threshold: {config.EDGE_THRESHOLD:.0%}\n"
        f"  Stop-loss: {config.STOP_LOSS_THRESHOLD:.0%}\n"
        f"  Max daily trades: {config.MAX_DAILY_TRADES}\n"
        f"  Discord: {'configured' if config.DISCORD_WEBHOOK_URL else 'NOT SET'}",
        title="PolyBot",
        style="bright_green",
    ))


def main() -> None:
    setup_logging()
    print_banner()

    if not config.DRY_RUN:
        console.print(
            "\n  [red bold]WARNING: LIVE MODE — real money will be used![/red bold]\n"
            "  Press Ctrl+C within 5 seconds to abort.\n"
        )
        import time
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)

    from pipeline import run_pipeline_v2
    run_pipeline_v2()


if __name__ == "__main__":
    main()
