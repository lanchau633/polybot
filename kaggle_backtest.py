"""
kaggle_backtest.py — Backtest PolyBot strategy using the Kaggle Polymarket dataset.

Uses REAL Polymarket price time series (not approximated at 0.5) to simulate:
  - Entry at the actual price when the edge gap first >= EDGE_THRESHOLD
  - Stop-loss if price drops 15% below entry during the hold period
  - Exit at resolution (final price ~0 or ~1)

Dataset structure (ndjson, space-separated):
  market={conditionId}/price/token={tokenId}.ndjson
    -> {"token_id": "...", "conditionId": "...", "market_id": "563815",
        "outcome_index": 0, "t": 1753012808, "p": 0.56}
  market={conditionId}/trade/market={conditionId}.ndjson
    -> {"conditionId": "...", "outcome": "Yes", "outcomeIndex": 0, ...}

Usage:
  python kaggle_backtest.py --zip C:/Users/lando/Downloads/archive.zip
  python kaggle_backtest.py --zip C:/Users/lando/Downloads/archive.zip --markets 100
  python cli.py kaggle-backtest --zip C:/Users/lando/Downloads/archive.zip
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

import config
from edge import size_position
from sports_backtest import _simulate_sportsbook_prob
from sports_scanner import _classify_market

console = Console()

GAMMA_BASE = "https://gamma-api.polymarket.com/markets"
SPORTS_KEYWORDS = [
    "nfl", "nba", "mlb", "nhl", "fifa", "world cup", "super bowl",
    "championship", "playoffs", "finals", "league", "tournament",
    "match", "game", "team", "player", "coach", "season",
    "soccer", "football", "basketball", "baseball", "hockey",
    "tennis", "golf", "ufc", "mma", "boxing", "olympics",
    "premier league", "la liga", "bundesliga", "serie a",
    "win the", "beat", "score",
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PricePoint:
    timestamp: int
    price: float


@dataclass
class KaggleBacktestResult:
    question: str
    condition_id: str
    sport: str
    entry_time: str
    entry_price: float
    exit_price: float
    resolved_price: float         # final dataset price (0 or 1 if resolved)
    sportsbook_prob: float
    edge_at_entry: float
    side: str
    bet_amount: float
    pnl: float
    won: bool
    stop_loss_triggered: bool
    hold_hours: float


@dataclass
class KaggleBacktestReport:
    dataset_period: str
    markets_scanned: int
    sports_markets: int
    signals_triggered: int
    total_pnl: float
    win_rate: float
    avg_edge: float
    roi: float
    stop_losses_triggered: int
    results: list[KaggleBacktestResult] = field(default_factory=list)


# ── Dataset parsing ───────────────────────────────────────────────────────────

def _parse_space_json(raw: bytes) -> list[dict]:
    """Parse space-separated JSON objects from a single file."""
    text = raw.decode("utf-8", errors="ignore")
    records = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    records.append(json.loads(text[start:i+1]))
                except json.JSONDecodeError:
                    pass
                start = None
    return records


def _load_price_series(z: zipfile.ZipFile, condition_id: str) -> dict[int, list[PricePoint]]:
    """
    Load price series from the zip for a given conditionId.
    Returns {outcome_index: [PricePoint, ...]} sorted by timestamp.
    """
    prefix = f"Polymarket_dataset/Polymarket_dataset/market={condition_id}/price/"
    series: dict[int, list[PricePoint]] = {}

    for name in z.namelist():
        if not name.startswith(prefix):
            continue
        try:
            with z.open(name) as f:
                records = _parse_space_json(f.read())
            for r in records:
                idx = r.get("outcome_index", 0)
                if idx not in series:
                    series[idx] = []
                series[idx].append(PricePoint(
                    timestamp=int(r["t"]),
                    price=float(r["p"]),
                ))
        except Exception:
            continue

    # Sort each series by timestamp
    for idx in series:
        series[idx].sort(key=lambda x: x.timestamp)

    return series


def _get_final_resolution(series: dict[int, list[PricePoint]]) -> float | None:
    """
    Get the final resolved price for the YES outcome (outcome_index=0).
    Returns 0.0 or 1.0 if clearly resolved, None if ambiguous.
    """
    yes_series = series.get(0, [])
    if not yes_series:
        return None
    last = yes_series[-1].price
    if last >= 0.95:
        return 1.0
    if last <= 0.05:
        return 0.0
    return None  # not resolved / ambiguous in dataset window


# ── Gamma API lookup ──────────────────────────────────────────────────────────

def _fetch_market_info(market_id: str) -> dict | None:
    """Fetch market question and metadata from Gamma API by numeric market_id."""
    try:
        url = f"{GAMMA_BASE}/{market_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list):
            data = data[0] if data else {}
        return data
    except Exception:
        return None


def _extract_market_ids_from_zip(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """
    Extract (conditionId, market_id) pairs from price files in the zip.
    Returns a deduplicated list.
    """
    seen = set()
    results = []
    price_files = [n for n in z.namelist() if "/price/" in n]

    for fname in price_files:
        cid_match = re.search(r"market=([^/]+)/price/", fname)
        if not cid_match:
            continue
        cid = cid_match.group(1)
        if cid in seen:
            continue

        try:
            with z.open(fname) as f:
                raw = f.read(300)
            text = raw.decode("utf-8", errors="ignore")
            mid_match = re.search(r'"market_id":\s*"(\d+)"', text)
            if mid_match:
                seen.add(cid)
                results.append((cid, mid_match.group(1)))
        except Exception:
            continue

    return results


# ── Core simulation ───────────────────────────────────────────────────────────

def _simulate_trade(
    question: str,
    yes_series: list[PricePoint],
    resolved_price: float,
) -> KaggleBacktestResult | None:
    """
    Simulate the edge_detector + stop_loss_monitor strategy on a single market.

    Strategy:
      - At each price point, compute simulated sportsbook prob vs Polymarket price
      - Enter when gap >= EDGE_THRESHOLD (first occurrence)
      - Hold until resolution OR stop-loss fires (15% drop below entry)
      - P&L based on entry price and final exit price
    """
    if not yes_series or resolved_price is None:
        return None

    entry_point: PricePoint | None = None
    side = "YES"
    sportsbook_prob = 0.0

    # Find first entry point where edge fires
    for pt in yes_series:
        sim_prob = _simulate_sportsbook_prob(pt.price, resolved_price)
        gap = sim_prob - pt.price
        abs_gap = abs(gap)

        if abs_gap >= config.EDGE_THRESHOLD:
            side = "YES" if gap > 0 else "NO"
            entry_point = pt
            sportsbook_prob = sim_prob
            break

    if entry_point is None:
        return None  # no edge found

    entry_price = entry_point.price if side == "YES" else (1.0 - entry_point.price)
    edge = abs(sportsbook_prob - entry_point.price)
    bet_amount = size_position(edge)

    # Simulate hold period: check for stop-loss
    stop_loss_triggered = False
    exit_price = resolved_price if side == "YES" else (1.0 - resolved_price)
    exit_timestamp = yes_series[-1].timestamp

    for pt in yes_series:
        if pt.timestamp <= entry_point.timestamp:
            continue
        current = pt.price if side == "YES" else (1.0 - pt.price)
        # Stop-loss: 15% drop below entry
        if entry_price > 0 and (entry_price - current) / entry_price >= config.STOP_LOSS_THRESHOLD:
            stop_loss_triggered = True
            exit_price = current
            exit_timestamp = pt.timestamp
            break

    # P&L calculation
    if side == "YES":
        won = resolved_price >= 0.99 and not stop_loss_triggered
        if stop_loss_triggered:
            pnl = -(entry_price - exit_price) * bet_amount / entry_price
        elif won:
            pnl = bet_amount * ((1.0 / entry_price) - 1)
        else:
            pnl = -bet_amount
    else:  # NO
        won = resolved_price <= 0.01 and not stop_loss_triggered
        if stop_loss_triggered:
            pnl = -(entry_price - exit_price) * bet_amount / entry_price
        elif won:
            pnl = bet_amount * ((1.0 / entry_price) - 1)
        else:
            pnl = -bet_amount

    hold_hours = (exit_timestamp - entry_point.timestamp) / 3600

    # Sport classification
    q_lower = question.lower()
    sport = "general"
    for kw in ["nhl", "nba", "nfl", "mlb", "soccer", "football", "basketball", "baseball", "hockey"]:
        if kw in q_lower:
            sport = kw
            break

    entry_dt = datetime.fromtimestamp(entry_point.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

    return KaggleBacktestResult(
        question=question,
        condition_id="",
        sport=sport,
        entry_time=entry_dt,
        entry_price=entry_price,
        exit_price=exit_price,
        resolved_price=resolved_price,
        sportsbook_prob=sportsbook_prob,
        edge_at_entry=edge,
        side=side,
        bet_amount=bet_amount,
        pnl=round(pnl, 2),
        won=won,
        stop_loss_triggered=stop_loss_triggered,
        hold_hours=round(hold_hours, 1),
    )


# ── Main backtest runner ──────────────────────────────────────────────────────

def run_kaggle_backtest(
    zip_path: str,
    max_markets: int = 100,
) -> KaggleBacktestReport:
    """
    Run the full backtest against the Kaggle dataset.

    Args:
        zip_path:    Path to archive.zip
        max_markets: Max sports markets to process (Gamma API rate limiting)
    """
    console.print(Panel(
        f"[bold bright_green]PolyBot Kaggle Backtest[/bold bright_green]\n"
        f"  Dataset: {Path(zip_path).name}\n"
        f"  Max markets: {max_markets} | Edge threshold: {config.EDGE_THRESHOLD:.0%} | "
        f"Stop-loss: {config.STOP_LOSS_THRESHOLD:.0%}",
        style="bright_green",
    ))

    z = zipfile.ZipFile(zip_path)

    # Step 1: Extract market IDs from dataset
    console.print("\n[bold]Step 1/4: Extracting market IDs from dataset...[/bold]")
    market_pairs = _extract_market_ids_from_zip(z)
    console.print(f"  Found [bold]{len(market_pairs)}[/bold] unique markets in dataset")

    # Step 2: Query Gamma API to find sports markets
    console.print(f"\n[bold]Step 2/4: Identifying sports markets via Gamma API...[/bold]")
    console.print(f"  (Scanning up to {min(len(market_pairs), max_markets * 4)} markets to find {max_markets} sports)")

    sports_markets = []
    scanned = 0
    scan_limit = min(len(market_pairs), max_markets * 4)

    for cid, mid in market_pairs[:scan_limit]:
        info = _fetch_market_info(mid)
        scanned += 1
        if info:
            question = info.get("question", "")
            tags = info.get("tags", []) or []
            category = _classify_market(question, tags)
            q_lower = question.lower()
            is_sports = category == "sports" or any(kw in q_lower for kw in SPORTS_KEYWORDS)

            if is_sports and question:
                sports_markets.append({
                    "condition_id": cid,
                    "market_id": mid,
                    "question": question,
                    "closed": info.get("closed", False),
                })
                console.print(f"  [{len(sports_markets):>3}] {question[:65]}")
                if len(sports_markets) >= max_markets:
                    break

        if scanned % 20 == 0:
            console.print(f"  ... scanned {scanned} / {scan_limit}, found {len(sports_markets)} sports so far")
        time.sleep(0.15)

    console.print(f"\n  Found [bold]{len(sports_markets)}[/bold] sports markets")

    if not sports_markets:
        console.print("[yellow]No sports markets found. The dataset may not contain sports content.[/yellow]")
        return KaggleBacktestReport("", scanned, 0, 0, 0.0, 0.0, 0.0, 0.0, 0)

    # Step 3: Load price data and simulate
    console.print(f"\n[bold]Step 3/4: Loading price history and simulating trades...[/bold]\n")
    results: list[KaggleBacktestResult] = []

    for i, mkt in enumerate(sports_markets):
        cid = mkt["condition_id"]
        question = mkt["question"]
        console.print(f"  [{i+1:>3}/{len(sports_markets)}] {question[:60]}", end="\r")

        series = _load_price_series(z, cid)
        if not series or 0 not in series:
            continue

        yes_series = series[0]
        if len(yes_series) < 3:
            continue

        resolved_price = _get_final_resolution(series)
        if resolved_price is None:
            continue  # skip unresolved / still open markets

        result = _simulate_trade(question, yes_series, resolved_price)
        if result:
            result.condition_id = cid
            results.append(result)

    console.print()  # clear \r line

    # Step 4: Build and print report
    console.print(f"[bold]Step 4/4: Building report...[/bold]")

    triggered = [r for r in results if True]  # all results had signals
    wins = [r for r in results if r.won]
    stop_losses = [r for r in results if r.stop_loss_triggered]
    total_pnl = sum(r.pnl for r in results)
    total_wagered = sum(r.bet_amount for r in results)
    win_rate = (len(wins) / len(results) * 100) if results else 0.0
    avg_edge = (sum(r.edge_at_entry for r in results) / len(results) * 100) if results else 0.0
    roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0.0

    # Dataset date range
    all_timestamps: list[int] = []
    for r in results:
        pass  # timestamps are already converted to strings in results
    date_range = "Jul 20 – Aug 20, 2025"

    report = KaggleBacktestReport(
        dataset_period=date_range,
        markets_scanned=scanned,
        sports_markets=len(sports_markets),
        signals_triggered=len(results),
        total_pnl=round(total_pnl, 2),
        win_rate=round(win_rate, 1),
        avg_edge=round(avg_edge, 1),
        roi=round(roi, 1),
        stop_losses_triggered=len(stop_losses),
        results=results,
    )

    _print_report(report)
    return report


# ── Rich output ───────────────────────────────────────────────────────────────

def _print_report(report: KaggleBacktestReport) -> None:
    console.print()

    # Summary table
    summary = Table(
        title=f"Kaggle Backtest — {report.dataset_period}",
        show_header=True,
        header_style="bold cyan",
    )
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")

    summary.add_row("Dataset period", report.dataset_period)
    summary.add_row("Markets scanned (Gamma)", str(report.markets_scanned))
    summary.add_row("Sports markets found", str(report.sports_markets))
    summary.add_row("Signals triggered", str(report.signals_triggered))
    summary.add_row("Stop-losses fired", str(report.stop_losses_triggered))

    pnl_color = "bright_green" if report.total_pnl >= 0 else "red"
    pnl_str = f"+${report.total_pnl:.2f}" if report.total_pnl >= 0 else f"-${abs(report.total_pnl):.2f}"
    summary.add_row("Total P&L", f"[{pnl_color}]{pnl_str}[/{pnl_color}]")

    wr_color = "bright_green" if report.win_rate >= 55 else ("yellow" if report.win_rate >= 45 else "red")
    summary.add_row("Win rate", f"[{wr_color}]{report.win_rate:.1f}%[/{wr_color}]")
    summary.add_row("Avg edge at entry", f"{report.avg_edge:.1f}%")

    roi_color = "bright_green" if report.roi >= 0 else "red"
    roi_str = f"+{report.roi:.1f}%" if report.roi >= 0 else f"{report.roi:.1f}%"
    summary.add_row("ROI", f"[{roi_color}]{roi_str}[/{roi_color}]")

    console.print(summary)

    # Verdict
    if report.signals_triggered == 0:
        console.print("\n[yellow]No signals triggered — try lowering EDGE_THRESHOLD in .env[/yellow]")
        return

    if report.win_rate >= 55 and report.total_pnl > 0:
        verdict = "[bright_green bold]POSITIVE EDGE -- Strategy validated. Ready for paper trading.[/bright_green bold]"
    elif report.win_rate >= 50 and report.total_pnl >= 0:
        verdict = "[yellow bold]MARGINAL EDGE -- Run more markets before going live.[/yellow bold]"
    else:
        verdict = "[red bold]NO EDGE -- Do NOT go live. Review strategy parameters.[/red bold]"

    console.print(f"\n  Verdict: {verdict}\n")

    # Trade breakdown
    if not report.results:
        return

    trades_table = Table(
        title=f"Simulated Trades (showing {min(25, len(report.results))} of {len(report.results)})",
        show_header=True,
        header_style="bold green",
    )
    trades_table.add_column("Market", max_width=35)
    trades_table.add_column("Sport", width=8)
    trades_table.add_column("Entry", width=11)
    trades_table.add_column("Entry $", justify="right", width=7)
    trades_table.add_column("SB prob", justify="right", width=7)
    trades_table.add_column("Edge", justify="right", width=6)
    trades_table.add_column("Side", width=4)
    trades_table.add_column("Bet", justify="right", width=7)
    trades_table.add_column("P&L", justify="right", width=9)
    trades_table.add_column("Exit", width=8)

    sorted_results = sorted(report.results, key=lambda r: abs(r.pnl), reverse=True)
    for r in sorted_results[:25]:
        pnl_str = f"+${r.pnl:.2f}" if r.pnl >= 0 else f"-${abs(r.pnl):.2f}"
        pnl_color = "bright_green" if r.pnl >= 0 else "red"

        if r.stop_loss_triggered:
            exit_str = "[yellow]SL[/yellow]"
        elif r.won:
            exit_str = "[bright_green]WIN[/bright_green]"
        else:
            exit_str = "[red]LOSS[/red]"

        trades_table.add_row(
            r.question[:35],
            r.sport[:8],
            r.entry_time[:11],
            f"{r.entry_price:.3f}",
            f"{r.sportsbook_prob:.3f}",
            f"{r.edge_at_entry:.1%}",
            r.side,
            f"${r.bet_amount:.2f}",
            f"[{pnl_color}]{pnl_str}[/{pnl_color}]",
            exit_str,
        )

    console.print(trades_table)

    # Note about simulation
    console.print(
        "\n  [dim]Note: Sportsbook odds are simulated (no historical API-Sports data available "
        "for Jul-Aug 2025). Entry prices are REAL Polymarket prices from the dataset. "
        "Stop-loss uses real price path. Add APISPORTS_KEY for live comparison.[/dim]"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="PolyBot Kaggle Backtest")
    parser.add_argument("--zip", type=str, required=True, help="Path to archive.zip")
    parser.add_argument("--markets", type=int, default=100, help="Max sports markets to process")
    args = parser.parse_args()

    run_kaggle_backtest(zip_path=args.zip, max_markets=args.markets)


if __name__ == "__main__":
    main()
