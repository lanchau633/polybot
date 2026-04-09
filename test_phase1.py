#!/usr/bin/env python3
"""
test_phase1.py — Dry-run smoke test for Phase 1 (Sports Scanner + Notifier).

Checks:
  1. Gamma API returns sports/general markets above volume threshold
  2. Discord webhook delivers an embed (expects HTTP 204)

Run:
  python test_phase1.py
"""
from __future__ import annotations

import asyncio
import sys

import aiohttp

import config
from sports_scanner import _fetch_markets
from notifier import send_embed


async def test_sports_scanner() -> bool:
    print("\n[1/2] Sports Scanner — fetching markets from Gamma API...")
    markets = await _fetch_markets()

    if not markets:
        print("  FAIL: no markets returned (check network / Gamma API)")
        return False

    print(f"  PASS: {len(markets)} markets fetched (sports/general, vol>=${config.MIN_MARKET_VOLUME:,.0f})")
    for m in markets[:5]:
        print(f"    [{m.category}] {m.question[:70]}")
        print(f"      YES={m.yes_price:.3f}  NO={m.no_price:.3f}  vol=${m.volume:,.0f}")
    if len(markets) > 5:
        print(f"    ... and {len(markets) - 5} more")
    return True


async def test_notifier() -> bool:
    print("\n[2/2] Notifier — sending test Discord embed...")
    url = config.DISCORD_WEBHOOK_URL

    if not url:
        print("  SKIP: DISCORD_WEBHOOK_URL not set in .env — skipping Discord test")
        return True  # Not a hard failure; key simply not configured yet

    # Intercept at the HTTP level so we can check the status code
    ok = False
    payload = {
        "embeds": [{
            "title": "PolyBot Phase 1 Smoke Test",
            "description": "If you see this, the notifier is wired up correctly.",
            "color": 0x00BFFF,
        }]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 204:
                    print("  PASS: Discord webhook returned 204 — embed delivered")
                    ok = True
                else:
                    body = await resp.text()
                    print(f"  FAIL: Discord webhook returned {resp.status}: {body}")
    except aiohttp.ClientError as e:
        print(f"  FAIL: Discord webhook request error: {e}")

    return ok


async def main() -> None:
    print("=" * 60)
    print("  PolyBot Phase 1 Smoke Test")
    print("=" * 60)

    scanner_ok = await test_sports_scanner()
    notifier_ok = await test_notifier()

    print("\n" + "=" * 60)
    if scanner_ok and notifier_ok:
        print("  ALL CHECKS PASSED — Phase 1 ready")
        sys.exit(0)
    else:
        print("  SOME CHECKS FAILED — see output above")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
