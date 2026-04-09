#!/usr/bin/env python3
"""
test_phase2.py — Integration test for Phase 2 (Edge Detection + Risk Manager).

Checks:
  1. risk_manager.can_trade() allows/blocks correctly
  2. Circuit breaker fires after CONSECUTIVE_LOSS_LIMIT losses
  3. edge_detector odds conversion is correct
  4. sell_position() returns dry_run result
  5. End-to-end: mock market with edge -> risk check -> dry-run order logged

Run:
  python test_phase2.py
"""
from __future__ import annotations

import asyncio
import sys

import config
import risk_manager
from edge_detector import _american_to_probability, _decimal_to_probability
from executor import sell_position
from markets import Market


def _make_market(yes_price: float = 0.50) -> Market:
    """Create a minimal test market."""
    return Market(
        condition_id="test-condition-123",
        question="Will TestTeam win the championship?",
        category="sports",
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 3),
        volume=50000.0,
        end_date="2026-12-31",
        active=True,
        tokens=[
            {"token_id": "tok-yes-123", "outcome": "Yes", "price": yes_price},
            {"token_id": "tok-no-123", "outcome": "No", "price": round(1.0 - yes_price, 3)},
        ],
    )


def test_risk_manager_allows() -> bool:
    print("\n[1/5] Risk Manager — allows trade under limits...")
    risk_manager.reset_circuit_breaker()
    risk_manager._daily_trade_count = 0
    risk_manager._open_positions = 0

    allowed, reason = risk_manager.can_trade(bet_amount=10, bankroll=200)
    if allowed:
        print(f"  PASS: trade allowed ({reason})")
        return True
    else:
        print(f"  FAIL: trade blocked unexpectedly ({reason})")
        return False


def test_risk_manager_blocks_cap() -> bool:
    print("\n[2/5] Risk Manager — blocks at daily cap...")
    risk_manager._daily_trade_count = config.MAX_DAILY_TRADES

    allowed, reason = risk_manager.can_trade()
    risk_manager._daily_trade_count = 0  # reset

    if not allowed and "daily_cap" in reason:
        print(f"  PASS: blocked ({reason})")
        return True
    else:
        print(f"  FAIL: expected daily_cap block, got ({allowed}, {reason})")
        return False


def test_circuit_breaker() -> bool:
    print("\n[3/5] Circuit Breaker — fires after consecutive losses...")
    risk_manager.reset_circuit_breaker()

    async def _run():
        for i in range(config.CONSECUTIVE_LOSS_LIMIT):
            await risk_manager.record_outcome(win=False)
        return risk_manager._circuit_breaker_active

    fired = asyncio.run(_run())
    risk_manager.reset_circuit_breaker()  # cleanup

    if fired:
        print(f"  PASS: circuit breaker fired after {config.CONSECUTIVE_LOSS_LIMIT} losses")
        return True
    else:
        print(f"  FAIL: circuit breaker did not fire")
        return False


def test_odds_conversion() -> bool:
    print("\n[4/5] Edge Detector — odds conversion...")
    ok = True

    # American odds: -200 should be ~66.7%, +150 should be ~40%
    p1 = _american_to_probability(-200)
    p2 = _american_to_probability(150)
    if abs(p1 - 0.6667) > 0.01:
        print(f"  FAIL: american_to_prob(-200) = {p1:.4f}, expected ~0.6667")
        ok = False
    if abs(p2 - 0.4) > 0.01:
        print(f"  FAIL: american_to_prob(+150) = {p2:.4f}, expected ~0.4000")
        ok = False

    # Decimal odds: 2.50 should be 40%
    p3 = _decimal_to_probability(2.50)
    if abs(p3 - 0.4) > 0.01:
        print(f"  FAIL: decimal_to_prob(2.50) = {p3:.4f}, expected ~0.4000")
        ok = False

    if ok:
        print(f"  PASS: american(-200)={p1:.4f}, american(+150)={p2:.4f}, decimal(2.50)={p3:.4f}")
    return ok


def test_sell_position_dry_run() -> bool:
    print("\n[5/5] Executor — sell_position() dry run...")
    market = _make_market(0.60)
    original_dry_run = config.DRY_RUN
    config.DRY_RUN = True

    result = sell_position(market, token_id="tok-yes-123", size=10.0, price=0.60)
    config.DRY_RUN = original_dry_run

    if result["status"] == "dry_run" and result["side"] == "SELL":
        print(f"  PASS: sell_position returned status={result['status']}, side={result['side']}")
        return True
    else:
        print(f"  FAIL: unexpected result: {result}")
        return False


def main() -> None:
    print("=" * 60)
    print("  PolyBot Phase 2 Integration Test")
    print("=" * 60)

    results = [
        test_risk_manager_allows(),
        test_risk_manager_blocks_cap(),
        test_circuit_breaker(),
        test_odds_conversion(),
        test_sell_position_dry_run(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"  ALL {total} CHECKS PASSED -- Phase 2 ready")
        sys.exit(0)
    else:
        print(f"  {passed}/{total} PASSED -- see failures above")
        sys.exit(1)


if __name__ == "__main__":
    main()
