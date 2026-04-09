"""
edge_detector.py — Compare Polymarket prices vs API-Sports sportsbook odds.

Reads markets from sports_scanner.market_queue, fetches real sportsbook odds
from API-Sports, and emits a Signal when the gap >= EDGE_THRESHOLD (8%).
"""
from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

import config
from edge import Signal, size_position
from markets import Market

logger = logging.getLogger(__name__)

APISPORTS_BASE = "https://v3.football.api-sports.io"

# Map common sport keywords to API-Sports endpoints
_SPORT_ENDPOINTS = {
    "football": "https://v3.football.api-sports.io",
    "soccer": "https://v3.football.api-sports.io",
    "basketball": "https://v1.basketball.api-sports.io",
    "nba": "https://v1.basketball.api-sports.io",
    "baseball": "https://v1.baseball.api-sports.io",
    "mlb": "https://v1.baseball.api-sports.io",
    "hockey": "https://v1.hockey.api-sports.io",
    "nhl": "https://v1.hockey.api-sports.io",
}


def _american_to_probability(odds: int) -> float:
    """Convert American odds (+150, -200) to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def _decimal_to_probability(odds: float) -> float:
    """Convert decimal odds (2.50) to implied probability."""
    if odds <= 0:
        return 0.0
    return 1.0 / odds


def _detect_sport(question: str) -> str | None:
    """Identify which sport a market question is about."""
    q = question.lower()
    for keyword, _ in _SPORT_ENDPOINTS.items():
        if keyword in q:
            return keyword
    # Broader heuristics
    if any(kw in q for kw in ["nfl", "touchdown", "quarterback", "super bowl"]):
        return "football"
    if any(kw in q for kw in ["premier league", "la liga", "champions league", "fifa", "world cup"]):
        return "soccer"
    if any(kw in q for kw in ["ufc", "mma", "boxing"]):
        return None  # API-Sports doesn't cover combat sports
    return None


def _extract_team_names(question: str) -> list[str]:
    """Best-effort extraction of team/player names from a market question."""
    # Pattern: "Will X win/beat Y", "X vs Y", "X to win"
    patterns = [
        r"[Ww]ill (.+?) (?:win|beat|defeat)",
        r"(.+?) vs\.? (.+?)[\?\.]",
        r"(.+?) to win",
    ]
    teams = []
    for pat in patterns:
        match = re.search(pat, question)
        if match:
            teams.extend(match.groups())
    # Clean up
    return [t.strip() for t in teams if t and len(t.strip()) > 2]


async def fetch_sportsbook_odds(market: Market) -> float | None:
    """
    Fetch sportsbook implied probability for a market from API-Sports.

    Returns the bookmaker's implied probability for the YES outcome,
    or None if no match / API error.
    """
    api_key = config.APISPORTS_KEY
    if not api_key:
        logger.debug("APISPORTS_KEY not set — skipping odds lookup")
        return None

    sport = _detect_sport(market.question)
    if not sport:
        return None

    base_url = _SPORT_ENDPOINTS.get(sport)
    if not base_url:
        return None

    teams = _extract_team_names(market.question)
    if not teams:
        return None

    headers = {
        "x-apisports-key": api_key,
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Search for fixtures matching team name
            search_term = teams[0][:30]  # API-Sports search limit
            async with session.get(
                f"{base_url}/fixtures",
                params={"search": search_term, "next": 10},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning("API-Sports returned %s for search '%s'", resp.status, search_term)
                    return None
                data = await resp.json(content_type=None)

            fixtures = data.get("response", [])
            if not fixtures:
                return None

            # Use the first matching fixture's ID to get odds
            fixture_id = fixtures[0].get("fixture", {}).get("id")
            if not fixture_id:
                return None

            async with session.get(
                f"{base_url}/odds",
                params={"fixture": fixture_id},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                odds_data = await resp.json(content_type=None)

            odds_list = odds_data.get("response", [])
            if not odds_list:
                return None

            # Find the "Match Winner" / "Home Win" market from any bookmaker
            for bookmaker_data in odds_list:
                for bookmaker in bookmaker_data.get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):
                        if bet.get("name") in ("Match Winner", "Home/Away", "Moneyline"):
                            for value in bet.get("values", []):
                                odds_val = value.get("odd")
                                if odds_val and value.get("value") in ("Home", "1", teams[0][:20]):
                                    return _decimal_to_probability(float(odds_val))

            return None

    except (aiohttp.ClientError, ValueError, KeyError) as e:
        logger.error("API-Sports fetch failed: %s", e)
        return None


async def detect_sports_edge(market: Market) -> Signal | None:
    """
    Compare Polymarket price vs sportsbook odds for a single market.
    Returns a Signal if gap >= EDGE_THRESHOLD, else None.
    """
    sportsbook_prob = await fetch_sportsbook_odds(market)
    if sportsbook_prob is None:
        return None

    polymarket_prob = market.yes_price
    gap = sportsbook_prob - polymarket_prob

    if abs(gap) < config.EDGE_THRESHOLD:
        return None

    if gap > 0:
        # Sportsbook says YES is more likely than Polymarket prices
        side = "YES"
        edge = gap
    else:
        # Sportsbook says NO is more likely
        side = "NO"
        edge = abs(gap)

    bet_amount = size_position(edge)

    logger.info(
        "EDGE: %s %s | polymarket=%.3f sportsbook=%.3f gap=%.1f%% bet=$%.2f",
        side, market.question[:50], polymarket_prob, sportsbook_prob, edge * 100, bet_amount,
    )

    return Signal(
        market=market,
        claude_score=sportsbook_prob,
        market_price=polymarket_prob,
        edge=edge,
        side=side,
        bet_amount=bet_amount,
        reasoning=f"Sportsbook prob {sportsbook_prob:.3f} vs Polymarket {polymarket_prob:.3f}",
        headlines="",
        news_source="api-sports",
        classification=side.lower(),
        materiality=edge,
    )


async def run(market_queue: asyncio.Queue, signal_queue: asyncio.Queue) -> None:
    """
    Main loop: reads markets from sports_scanner queue, checks for edge,
    pushes signals to the pipeline's signal queue.
    """
    logger.info("EdgeDetector started — waiting for markets from scanner")
    while True:
        market: Market = await market_queue.get()
        try:
            signal = await detect_sports_edge(market)
            if signal:
                await signal_queue.put(signal)
        except Exception as e:
            logger.error("EdgeDetector error on '%s': %s", market.question[:40], e)
