"""
risk_manager.py — Pre-trade gatekeeper for PolyBot.

Checks four constraints before every order:
  1. Daily trade count < MAX_DAILY_TRADES (50)
  2. Open positions < MAX_OPEN_POSITIONS (10)
  3. Cash reserve >= MIN_BANKROLL_RESERVE (10%)
  4. No active circuit breaker (5 consecutive losses)

Designed to be cleanly separable — disable by setting RISK_MANAGER_ENABLED=false
in .env, or simply stop calling can_trade().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
import notifier

logger = logging.getLogger(__name__)

# In-memory state (reset on process restart; trade counts come from SQLite)
_consecutive_losses: int = 0
_circuit_breaker_active: bool = False
_daily_trade_count: int = 0
_open_positions: int = 0
_last_reset_date: str = ""

# Toggle: set RISK_MANAGER_ENABLED=false in .env to bypass all checks
ENABLED = config.__dict__.get("RISK_MANAGER_ENABLED", True)
if isinstance(ENABLED, str):
    ENABLED = ENABLED.lower() != "false"


def can_trade(bet_amount: float = 0.0, bankroll: float = 0.0) -> tuple[bool, str]:
    """
    Check all risk constraints. Returns (allowed, reason).

    If RISK_MANAGER_ENABLED is false, always returns (True, "risk_manager_disabled").
    """
    if not ENABLED:
        return True, "risk_manager_disabled"

    _maybe_reset_daily()

    # 1. Circuit breaker
    if _circuit_breaker_active:
        return False, f"circuit_breaker (consecutive_losses={_consecutive_losses})"

    # 2. Daily trade cap
    if _daily_trade_count >= config.MAX_DAILY_TRADES:
        return False, f"daily_cap ({_daily_trade_count}/{config.MAX_DAILY_TRADES})"

    # 3. Max open positions
    if _open_positions >= config.MAX_OPEN_POSITIONS:
        return False, f"max_positions ({_open_positions}/{config.MAX_OPEN_POSITIONS})"

    # 4. Cash reserve
    if bankroll > 0 and bet_amount > 0:
        remaining = bankroll - bet_amount
        reserve_ratio = remaining / bankroll
        if reserve_ratio < config.MIN_BANKROLL_RESERVE:
            return False, f"cash_reserve ({reserve_ratio:.1%} < {config.MIN_BANKROLL_RESERVE:.0%})"

    return True, "ok"


def record_trade() -> None:
    """Call after a trade is successfully placed."""
    global _daily_trade_count
    _daily_trade_count += 1


def open_position() -> None:
    """Call when a new position is opened."""
    global _open_positions
    _open_positions += 1


def close_position() -> None:
    """Call when a position is closed (sell or stop-loss)."""
    global _open_positions
    _open_positions = max(0, _open_positions - 1)


async def record_outcome(win: bool) -> None:
    """
    Track consecutive losses. Triggers circuit breaker after
    CONSECUTIVE_LOSS_LIMIT losses in a row.
    """
    global _consecutive_losses, _circuit_breaker_active

    if win:
        _consecutive_losses = 0
        return

    _consecutive_losses += 1
    logger.warning("Consecutive loss #%d", _consecutive_losses)

    if _consecutive_losses >= config.CONSECUTIVE_LOSS_LIMIT:
        _circuit_breaker_active = True
        logger.error("CIRCUIT BREAKER ACTIVATED after %d consecutive losses", _consecutive_losses)
        await notifier.notify_circuit_breaker(_consecutive_losses)


def reset_circuit_breaker() -> None:
    """Manually reset the circuit breaker (also resets at midnight UTC)."""
    global _consecutive_losses, _circuit_breaker_active
    _consecutive_losses = 0
    _circuit_breaker_active = False
    logger.info("Circuit breaker reset")


def _maybe_reset_daily() -> None:
    """Reset daily counters if the UTC date has changed."""
    global _daily_trade_count, _last_reset_date, _circuit_breaker_active, _consecutive_losses
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _last_reset_date:
        _daily_trade_count = 0
        _consecutive_losses = 0
        _circuit_breaker_active = False
        _last_reset_date = today


def get_status() -> dict:
    """Return current risk manager state for debugging / status display."""
    _maybe_reset_daily()
    return {
        "enabled": ENABLED,
        "daily_trades": _daily_trade_count,
        "max_daily_trades": config.MAX_DAILY_TRADES,
        "open_positions": _open_positions,
        "max_open_positions": config.MAX_OPEN_POSITIONS,
        "consecutive_losses": _consecutive_losses,
        "circuit_breaker_active": _circuit_breaker_active,
    }
