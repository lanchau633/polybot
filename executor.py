from __future__ import annotations

import asyncio

import config
import logger
from edge import Signal
from markets import get_token_id


def execute_trade(signal: Signal) -> dict:
    """Execute a trade on Polymarket or log a dry-run. Synchronous."""
    daily_spent = abs(logger.get_daily_pnl())
    if daily_spent + signal.bet_amount > config.DAILY_LOSS_LIMIT_USD:
        return _log_and_return(signal, status="rejected_daily_limit", order_id=None)

    if config.DRY_RUN:
        return _log_and_return(signal, status="dry_run", order_id=None)

    return _execute_live(signal)


async def execute_trade_async(signal: Signal) -> dict:
    """Async wrapper around execute_trade."""
    return await asyncio.get_event_loop().run_in_executor(None, execute_trade, signal)


def _execute_live(signal: Signal) -> dict:
    """Place a real order via Polymarket CLOB client."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = ClobClient(
            host=config.POLYMARKET_HOST,
            key=config.POLYMARKET_API_KEY,
            chain_id=137,
            funder=config.POLYMARKET_PRIVATE_KEY,
        )

        client.set_api_creds(client.create_or_derive_api_creds())

        token_id = get_token_id(signal.market, signal.side)
        if not token_id:
            return _log_and_return(signal, status="error_no_token", order_id=None)

        price = signal.market.yes_price if signal.side == "YES" else signal.market.no_price

        order_args = OrderArgs(
            price=price,
            size=signal.bet_amount,
            side="BUY",
            token_id=token_id,
        )

        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)

        order_id = resp.get("orderID", resp.get("id", "unknown"))
        return _log_and_return(signal, status="executed", order_id=order_id)

    except ImportError:
        return _log_and_return(signal, status="error_no_clob_client", order_id=None)
    except Exception as e:
        return _log_and_return(signal, status=f"error_{type(e).__name__}", order_id=None)


def sell_position(market, token_id: str, size: float, price: float) -> dict:
    """Place a SELL order for an open position. Respects DRY_RUN."""
    result = {
        "market": market.question,
        "side": "SELL",
        "amount": size,
        "token_id": token_id,
        "price": price,
        "status": "dry_run",
        "order_id": None,
    }

    if config.DRY_RUN:
        result["status"] = "dry_run"
        return result

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = ClobClient(
            host=config.POLYMARKET_HOST,
            key=config.POLYMARKET_API_KEY,
            chain_id=137,
            funder=config.POLYMARKET_PRIVATE_KEY,
        )
        client.set_api_creds(client.create_or_derive_api_creds())

        order_args = OrderArgs(
            price=price,
            size=size,
            side="SELL",
            token_id=token_id,
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)

        result["order_id"] = resp.get("orderID", resp.get("id", "unknown"))
        result["status"] = "executed"
    except ImportError:
        result["status"] = "error_no_clob_client"
    except Exception as e:
        result["status"] = f"error_{type(e).__name__}"

    return result


async def sell_position_async(market, token_id: str, size: float, price: float) -> dict:
    """Async wrapper around sell_position."""
    return await asyncio.get_event_loop().run_in_executor(
        None, sell_position, market, token_id, size, price
    )


def _log_and_return(signal: Signal, status: str, order_id: str | None) -> dict:
    """Log trade to SQLite and return result dict."""
    trade_id = logger.log_trade(
        market_id=signal.market.condition_id,
        market_question=signal.market.question,
        claude_score=signal.claude_score,
        market_price=signal.market_price,
        edge=signal.edge,
        side=signal.side,
        amount_usd=signal.bet_amount,
        order_id=order_id,
        status=status,
        reasoning=signal.reasoning,
        headlines=signal.headlines,
        news_source=signal.news_source,
        classification=signal.classification,
        materiality=signal.materiality,
        news_latency_ms=signal.news_latency_ms,
        classification_latency_ms=signal.classification_latency_ms,
        total_latency_ms=signal.total_latency_ms,
    )

    return {
        "trade_id": trade_id,
        "market": signal.market.question,
        "side": signal.side,
        "amount": signal.bet_amount,
        "edge": signal.edge,
        "status": status,
        "order_id": order_id,
        "classification": signal.classification,
        "materiality": signal.materiality,
        "latency_ms": signal.total_latency_ms,
    }
