"""
stop_loss_monitor.py — Polls open positions every 10s, triggers FOK sell
if price drops >= STOP_LOSS_THRESHOLD (15%) below entry.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

import config
import notifier
import risk_manager
from executor import sell_position_async
from markets import Market

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
POLL_INTERVAL = 10  # seconds


@dataclass
class TrackedPosition:
    market: Market
    token_id: str
    side: str
    size: float
    entry_price: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# In-memory position tracker
_positions: dict[str, TrackedPosition] = {}


def track_position(market: Market, token_id: str, side: str, size: float, entry_price: float) -> None:
    """Register a new position for stop-loss monitoring."""
    key = f"{market.condition_id}:{side}"
    _positions[key] = TrackedPosition(
        market=market,
        token_id=token_id,
        side=side,
        size=size,
        entry_price=entry_price,
    )
    logger.info("Tracking position: %s %s entry=%.3f size=%.2f",
                side, market.question[:40], entry_price, size)


def untrack_position(condition_id: str, side: str) -> None:
    """Remove a position from monitoring (after sell or resolution)."""
    key = f"{condition_id}:{side}"
    _positions.pop(key, None)


def get_tracked_positions() -> list[TrackedPosition]:
    """Return all currently tracked positions."""
    return list(_positions.values())


async def _fetch_current_price(condition_id: str) -> float | None:
    """Fetch the current YES midpoint for a market from Gamma API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GAMMA_URL}/{condition_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)

                # Parse outcomePrices
                import json
                outcome_prices = data.get("outcomePrices", "")
                if outcome_prices:
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if len(prices) >= 2:
                        return float(prices[0])  # YES price
                return None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        logger.debug("Price fetch failed for %s: %s", condition_id, e)
        return None


def should_stop_loss(entry_price: float, current_price: float) -> bool:
    """Return True if the drop from entry >= STOP_LOSS_THRESHOLD."""
    if entry_price <= 0:
        return False
    drop = (entry_price - current_price) / entry_price
    # Small epsilon to handle floating-point rounding at exact boundary
    return drop >= config.STOP_LOSS_THRESHOLD - 1e-9


async def _check_position(key: str, pos: TrackedPosition) -> None:
    """Check a single position and trigger stop-loss if needed."""
    current_price = await _fetch_current_price(pos.market.condition_id)
    if current_price is None:
        return

    # For NO side, we care about the inverse price movement
    if pos.side == "NO":
        effective_entry = 1.0 - pos.entry_price
        effective_current = 1.0 - current_price
    else:
        effective_entry = pos.entry_price
        effective_current = current_price

    if not should_stop_loss(effective_entry, effective_current):
        return

    # STOP-LOSS TRIGGERED
    logger.warning(
        "STOP-LOSS: %s %s entry=%.3f current=%.3f",
        pos.side, pos.market.question[:40], pos.entry_price, current_price,
    )

    # Execute FOK sell
    sell_price = current_price if pos.side == "YES" else (1.0 - current_price)
    result = await sell_position_async(
        market=pos.market,
        token_id=pos.token_id,
        size=pos.size,
        price=sell_price,
    )
    logger.info("Stop-loss sell result: %s", result["status"])

    # Only untrack and record loss if the sell actually succeeded
    if result["status"] in ("dry_run", "executed"):
        await notifier.notify_stop_loss(
            market=pos.market.question,
            entry_price=pos.entry_price,
            current_price=current_price,
        )
        risk_manager.close_position()
        await risk_manager.record_outcome(win=False)
        _positions.pop(key, None)
    else:
        # Sell failed — keep tracking so we retry next cycle
        logger.error("Stop-loss sell FAILED (%s), position still tracked: %s",
                      result["status"], pos.market.question[:40])


async def run() -> None:
    """Main loop — polls all tracked positions every POLL_INTERVAL seconds."""
    logger.info("StopLossMonitor started (interval=%ds, threshold=%.0f%%)",
                POLL_INTERVAL, config.STOP_LOSS_THRESHOLD * 100)
    while True:
        if _positions:
            # Snapshot keys to avoid mutation during iteration
            keys = list(_positions.keys())
            for key in keys:
                pos = _positions.get(key)
                if pos:
                    await _check_position(key, pos)
        await asyncio.sleep(POLL_INTERVAL)
