"""
daily_report.py — End-of-day P&L summary posted to Discord (blue embed).

Runs as a background task: sleeps until midnight UTC, then queries SQLite
for the day's trades and sends a summary via notifier.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import logger as db_logger
import notifier

log = logging.getLogger(__name__)


def _seconds_until_midnight_utc() -> float:
    """Return seconds remaining until next midnight UTC."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def build_daily_summary() -> dict:
    """
    Query SQLite for today's trading activity.

    Returns dict with: date, total_trades, wins, losses, pnl, markets_scanned.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trades = db_logger.get_recent_trades(limit=500)

    # Filter to today's trades
    today_trades = [t for t in trades if t.get("created_at", "").startswith(today)]

    total = len(today_trades)
    executed = [t for t in today_trades if t["status"] in ("dry_run", "executed")]

    # Estimate P&L from trade amounts (actual P&L requires resolution data)
    total_spent = sum(t.get("amount_usd", 0) for t in executed)

    # Count wins/losses from outcomes table if available
    wins = sum(1 for t in today_trades if t["status"] == "executed")
    losses = sum(1 for t in today_trades if "error" in t.get("status", ""))

    return {
        "date": today,
        "total_trades": total,
        "executed": len(executed),
        "wins": wins,
        "losses": losses,
        "total_spent": total_spent,
        "pnl": db_logger.get_daily_pnl(),
    }


async def send_report_now() -> dict:
    """Build and send the daily report immediately. Returns the summary dict."""
    summary = build_daily_summary()

    description_lines = [
        f"**Date:** {summary['date']}",
        f"**Trades:** {summary['total_trades']}",
        f"**Executed:** {summary['executed']}",
        f"**Total spent:** ${summary['total_spent']:.2f}",
    ]

    pnl = summary["pnl"]
    sign = "+" if pnl >= 0 else ""
    description_lines.append(f"**P&L:** {sign}${pnl:.2f}")

    await notifier.notify_daily_summary(
        pnl=pnl,
        trades=summary["total_trades"],
    )

    log.info("Daily report sent: %s", summary)
    return summary


async def run() -> None:
    """Main loop — sends daily report at midnight UTC, then repeats."""
    log.info("DailyReport started — will fire at midnight UTC each day")
    while True:
        wait = _seconds_until_midnight_utc()
        log.info("DailyReport sleeping %.0f seconds until midnight UTC", wait)
        await asyncio.sleep(wait)

        try:
            await send_report_now()
        except Exception as e:
            log.error("DailyReport failed: %s", e)

        # Small buffer to avoid firing twice at exactly midnight
        await asyncio.sleep(5)
