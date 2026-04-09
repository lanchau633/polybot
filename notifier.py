"""
notifier.py — Discord webhook notifications for PolyBot.

All functions are fire-and-forget async; failures are logged, never raised.
"""
from __future__ import annotations

import logging

import aiohttp

import config

logger = logging.getLogger(__name__)

# Color constants (Discord embed decimal values)
_COLOR_TRADE = 0x00FF00            # green
_COLOR_STOP_LOSS = 0xFF0000        # red
_COLOR_CIRCUIT_BREAKER = 0xFF0000  # red
_COLOR_DAILY_SUMMARY = 0x0000FF   # blue


async def send_embed(title: str, description: str, color: int) -> None:
    """POST a Discord embed to the configured webhook URL. Silently logs on failure."""
    url = config.DISCORD_WEBHOOK_URL
    if not url:
        logger.warning("DISCORD_WEBHOOK_URL not set — skipping notification")
        return

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
        }]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 204:
                    body = await resp.text()
                    logger.error("Discord webhook returned %s: %s", resp.status, body)
    except aiohttp.ClientError as e:
        logger.error("Discord webhook request failed: %s", e)


async def notify_trade(market: str, side: str, amount: float, edge: float) -> None:
    """Green embed — a trade was executed (or dry-run logged)."""
    await send_embed(
        title="Trade Executed",
        description=(
            f"**Market:** {market}\n"
            f"**Side:** {side.upper()}\n"
            f"**Amount:** ${amount:.2f}\n"
            f"**Edge:** {edge:.1%}"
        ),
        color=_COLOR_TRADE,
    )


async def notify_stop_loss(market: str, entry_price: float, current_price: float) -> None:
    """Red embed — stop-loss triggered on an open position."""
    drop_pct = (entry_price - current_price) / entry_price
    await send_embed(
        title="Stop-Loss Triggered",
        description=(
            f"**Market:** {market}\n"
            f"**Entry price:** {entry_price:.3f}\n"
            f"**Current price:** {current_price:.3f}\n"
            f"**Drop:** {drop_pct:.1%}"
        ),
        color=_COLOR_STOP_LOSS,
    )


async def notify_circuit_breaker(consecutive_losses: int) -> None:
    """Red embed — circuit breaker halted trading after N consecutive losses."""
    await send_embed(
        title="Circuit Breaker Activated",
        description=(
            f"Trading halted after **{consecutive_losses} consecutive losses**.\n"
            "Will reset at midnight UTC."
        ),
        color=_COLOR_CIRCUIT_BREAKER,
    )


async def notify_daily_summary(pnl: float, trades: int) -> None:
    """Blue embed — end-of-day P&L summary."""
    sign = "+" if pnl >= 0 else ""
    await send_embed(
        title="Daily Summary",
        description=(
            f"**P&L:** {sign}${pnl:.2f}\n"
            f"**Trades today:** {trades}"
        ),
        color=_COLOR_DAILY_SUMMARY,
    )
