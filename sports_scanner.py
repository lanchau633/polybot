"""
sports_scanner.py — Polls Gamma API every 60s for sports/general markets.

Filters by $10K+ 24h volume and sports/general tags, then pushes candidates
into a shared asyncio.Queue for downstream edge detection.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiohttp

import config
import notifier
from markets import Market

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"

# Keywords used to classify a market as sports or general
_SPORTS_KEYWORDS = [
    "nfl", "nba", "mlb", "nhl", "fifa", "world cup", "super bowl",
    "championship", "playoffs", "finals", "league", "tournament",
    "match", "game", "team", "player", "coach", "season",
    "soccer", "football", "basketball", "baseball", "hockey",
    "tennis", "golf", "ufc", "mma", "boxing", "olympics",
    "premier league", "la liga", "bundesliga", "serie a",
]

_GENERAL_KEYWORDS = [
    "will ", "who will", "when will", "how many", "what will",
]


def _classify_market(question: str, tags: list) -> str | None:
    """Return 'sports', 'general', or None (not relevant)."""
    q = question.lower()
    tag_str = " ".join(str(t).lower() for t in tags)
    combined = f"{q} {tag_str}"

    if any(kw in combined for kw in _SPORTS_KEYWORDS):
        return "sports"
    # General: broad prediction markets that aren't already categorised
    if any(kw in combined for kw in _GENERAL_KEYWORDS):
        return "general"
    return None


def _parse_market(raw: dict) -> Market | None:
    """Parse a raw Gamma API dict into a Market. Returns None on bad data."""
    try:
        outcome_prices = raw.get("outcomePrices", "")
        yes_price, no_price = 0.5, 0.5
        if outcome_prices:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if len(prices) >= 2:
                yes_price = float(prices[0])
                no_price = float(prices[1])

        clob_ids = raw.get("clobTokenIds", "")
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except json.JSONDecodeError:
                clob_ids = []

        token_list = []
        for i, tid in enumerate(clob_ids if isinstance(clob_ids, list) else []):
            token_list.append({
                "token_id": tid,
                "outcome": "Yes" if i == 0 else "No",
                "price": yes_price if i == 0 else no_price,
            })

        vol = float(raw.get("volume", raw.get("volumeNum", 0)) or 0)
        question = raw.get("question", "")
        tags = raw.get("tags", []) or []

        category = _classify_market(question, tags)
        if category is None:
            return None

        if vol < config.MIN_MARKET_VOLUME:
            return None

        return Market(
            condition_id=raw.get("conditionId", raw.get("condition_id", raw.get("id", ""))),
            question=question,
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume=vol,
            end_date=raw.get("endDate", raw.get("end_date_iso", "")),
            active=raw.get("active", True),
            tokens=token_list,
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.debug("Failed to parse market: %s", e)
        return None


async def _fetch_markets() -> list[Market]:
    """Fetch and filter markets from Gamma API. Returns [] on error."""
    params = {
        "limit": 200,
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "ascending": "false",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GAMMA_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except aiohttp.ClientError as e:
        logger.error("Gamma API fetch failed: %s", e)
        return []

    items = data if isinstance(data, list) else data.get("data", [])
    markets: list[Market] = []
    for raw in items:
        m = _parse_market(raw)
        if m is not None:
            markets.append(m)

    markets.sort(key=lambda x: x.volume, reverse=True)
    return markets


class SportsScanner:
    """Polls Gamma API and pushes candidate markets into a queue."""

    def __init__(self, market_queue: asyncio.Queue):
        self.market_queue = market_queue
        self._first_run = True

    async def run(self) -> None:
        """Entry point — loops forever, polling every SPORTS_SCAN_INTERVAL seconds."""
        logger.info("SportsScanner started (interval=%ss, min_volume=$%,.0f)",
                    config.SPORTS_SCAN_INTERVAL, config.MIN_MARKET_VOLUME)
        while True:
            markets = await _fetch_markets()

            if markets:
                for m in markets:
                    await self.market_queue.put(m)
                logger.info("SportsScanner: queued %d markets (sports/general, vol≥$%,.0f)",
                            len(markets), config.MIN_MARKET_VOLUME)

                if self._first_run:
                    self._first_run = False
                    await notifier.send_embed(
                        title="PolyBot Sports Scanner Started",
                        description=(
                            f"Scanning every **{config.SPORTS_SCAN_INTERVAL}s**\n"
                            f"Min volume: **${config.MIN_MARKET_VOLUME:,.0f}**\n"
                            f"Markets found on first scan: **{len(markets)}**"
                        ),
                        color=0x00BFFF,  # info blue
                    )
            else:
                logger.warning("SportsScanner: no markets returned this cycle")

            await asyncio.sleep(config.SPORTS_SCAN_INTERVAL)


# Module-level queue and scanner instance (shared with pipeline.py)
market_queue: asyncio.Queue = asyncio.Queue()
_scanner = SportsScanner(market_queue)


async def run() -> None:
    """Convenience entry point for asyncio.gather in pipeline.py."""
    await _scanner.run()
