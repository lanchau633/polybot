#!/usr/bin/env python3
"""
test_phase3.py — Smoke test for Phase 3 (Stop-Loss Monitor + Daily Report).

Checks:
  1. should_stop_loss triggers at exactly 15% drop
  2. should_stop_loss does NOT trigger at 14.9% drop
  3. track/untrack positions work correctly
  4. daily_report.build_daily_summary() returns valid structure
  5. sell_position dry-run works for stop-loss scenario

Run:
  python test_phase3.py
"""
from __future__ import annotations

import sys

import config
from markets import Market
from stop_loss_monitor import should_stop_loss, track_position, untrack_position, get_tracked_positions
from daily_report import build_daily_summary
from executor import sell_position


def _make_market(yes_price: float = 0.60) -> Market:
    return Market(
        condition_id="test-sl-123",
        question="Will TestTeam win the finals?",
        category="sports",
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 3),
        volume=50000.0,
        end_date="2026-12-31",
        active=True,
        tokens=[
            {"token_id": "tok-yes-sl", "outcome": "Yes", "price": yes_price},
            {"token_id": "tok-no-sl", "outcome": "No", "price": round(1.0 - yes_price, 3)},
        ],
    )


def test_stop_loss_triggers() -> bool:
    print("\n[1/5] Stop-loss triggers at exactly 15% drop...")
    entry = 0.600
    # 15% drop from 0.600 = 0.510
    current = entry * (1 - config.STOP_LOSS_THRESHOLD)

    if should_stop_loss(entry, current):
        print(f"  PASS: triggered at entry={entry:.3f} current={current:.3f} (drop={config.STOP_LOSS_THRESHOLD:.0%})")
        return True
    else:
        print(f"  FAIL: did not trigger at exact threshold")
        return False


def test_stop_loss_no_trigger() -> bool:
    print("\n[2/5] Stop-loss does NOT trigger at 14.9% drop...")
    entry = 0.600
    # 14.9% drop — just under threshold
    current = entry * (1 - 0.149)

    if not should_stop_loss(entry, current):
        print(f"  PASS: correctly did NOT trigger at entry={entry:.3f} current={current:.3f} (drop=14.9%)")
        return True
    else:
        print(f"  FAIL: triggered when it should not have")
        return False


def test_position_tracking() -> bool:
    print("\n[3/5] Position tracking (track/untrack)...")
    # Clean slate
    from stop_loss_monitor import _positions
    _positions.clear()

    market = _make_market(0.60)
    track_position(market, "tok-yes-sl", "YES", 10.0, 0.60)

    positions = get_tracked_positions()
    if len(positions) != 1:
        print(f"  FAIL: expected 1 position, got {len(positions)}")
        return False

    untrack_position("test-sl-123", "YES")
    positions = get_tracked_positions()
    if len(positions) != 0:
        print(f"  FAIL: expected 0 positions after untrack, got {len(positions)}")
        return False

    print(f"  PASS: track/untrack works correctly")
    return True


def test_daily_summary() -> bool:
    print("\n[4/5] Daily report — build_daily_summary()...")
    summary = build_daily_summary()

    required_keys = ["date", "total_trades", "executed", "pnl"]
    missing = [k for k in required_keys if k not in summary]
    if missing:
        print(f"  FAIL: missing keys: {missing}")
        return False

    print(f"  PASS: summary has all required keys: date={summary['date']}, "
          f"trades={summary['total_trades']}, pnl=${summary['pnl']:.2f}")
    return True


def test_stop_loss_sell_dry_run() -> bool:
    print("\n[5/5] Stop-loss sell — dry run...")
    market = _make_market(0.60)
    original = config.DRY_RUN
    config.DRY_RUN = True

    result = sell_position(market, token_id="tok-yes-sl", size=10.0, price=0.51)
    config.DRY_RUN = original

    if result["status"] == "dry_run" and result["side"] == "SELL":
        print(f"  PASS: stop-loss sell returned status={result['status']}")
        return True
    else:
        print(f"  FAIL: unexpected result: {result}")
        return False


def main() -> None:
    print("=" * 60)
    print("  PolyBot Phase 3 Smoke Test")
    print("=" * 60)

    results = [
        test_stop_loss_triggers(),
        test_stop_loss_no_trigger(),
        test_position_tracking(),
        test_daily_summary(),
        test_stop_loss_sell_dry_run(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"  ALL {total} CHECKS PASSED -- Phase 3 ready")
        sys.exit(0)
    else:
        print(f"  {passed}/{total} PASSED -- see failures above")
        sys.exit(1)


if __name__ == "__main__":
    main()
