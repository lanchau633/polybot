# Polymarket Pipeline

An AI-powered news scraper that reads real-time headlines, scores confidence on Polymarket prediction markets using Claude, and places bets automatically when it finds edge.

```
RSS News Feeds → Claude Confidence Scoring → Edge Detection → Auto Trade Execution
```

The pipeline scrapes 5 news sources, fetches active Polymarket markets, asks Claude "given these headlines, what's the probability this resolves YES?", and when Claude's confidence diverges from the market price by 10%+ — it bets.

Everything is logged. Every trade, every reasoning chain, every headline that informed the decision.

---

## Setup (2 minutes)

### Option A: One-Command Setup

```bash
git clone https://github.com/brodyautomates/polymarket-pipeline.git
cd polymarket-pipeline
bash setup.sh
```

The setup script will:
- Check your Python version
- Create a virtual environment
- Install all dependencies
- Walk you through entering API keys
- Verify everything works

### Option B: Manual Setup

```bash
git clone https://github.com/brodyautomates/polymarket-pipeline.git
cd polymarket-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and add your keys:

```
ANTHROPIC_API_KEY=sk-ant-...    # Required — get one at console.anthropic.com
NEWSAPI_KEY=...                  # Optional — broader news coverage (newsapi.org)
POLYMARKET_API_KEY=...           # Optional — only needed for live trading
```

### Verify Your Setup

```bash
python cli.py verify
```

This checks every connection — Python version, dependencies, API keys, news scraper, Polymarket API, database. Fix anything marked FAIL before running the pipeline.

---

## How to Use

### Run the Pipeline

```bash
# Dry-run (default) — scans markets, scores with Claude, logs what it would bet
python cli.py run

# Scan more markets, look further back for news
python cli.py run --max 15 --hours 12

# Enable real trading (requires Polymarket credentials)
python cli.py run --live

# Lower the edge threshold (more trades, less conviction)
python cli.py run --threshold 0.08
```

### Launch the Live Dashboard

```bash
python cli.py dashboard
```

Full-screen terminal dashboard showing the pipeline scanning markets in real-time. News ticker, market scanner, trade log, performance stats — all updating live.

```bash
# Faster scan cycles (every 30 seconds instead of 60)
python cli.py dashboard --speed 30
```

### Other Commands

```bash
python cli.py scrape         # Test news scraper — see what headlines it pulls
python cli.py markets        # Browse active Polymarket markets with prices
python cli.py trades         # View your trade log
python cli.py stats          # Performance statistics
```

---

## How It Works

### 1. News Scraping (`scraper.py`)
Pulls headlines from 5 RSS feeds — Google News (AI), TechCrunch, Ars Technica, The Verge, NYT Technology. Optional NewsAPI integration for broader coverage. Deduplicates by headline similarity, filters by recency.

### 2. Market Fetching (`markets.py`)
Fetches active markets from Polymarket's Gamma API, sorted by volume. Categorizes each market (AI, crypto, politics, technology, science) by keyword matching on the question text.

### 3. Confidence Scoring (`scorer.py`)
For each market, filters relevant headlines and sends them to Claude with the prompt: *"Given these news articles, what is the probability that [market question] resolves YES?"*

Claude returns a confidence score (0.0–1.0) and a reasoning summary. The prompt explicitly tells Claude NOT to anchor to the current market price — we want an independent estimate.

### 4. Edge Detection (`edge.py`)
Compares Claude's confidence against the market's implied probability (YES token price). If they diverge by more than the threshold (default 10%), that's a signal.

- Claude says 0.75, market says 0.55 → **+20% edge → BUY YES**
- Claude says 0.30, market says 0.55 → **-25% edge → BUY NO**

Position sizing uses quarter-Kelly criterion — conservative enough to survive variance.

### 5. Trade Execution (`executor.py`)
In dry-run mode: logs what it would have bet. In live mode: places limit orders through Polymarket's CLOB API. Safety rails enforce max bet ($25), daily loss limit ($100), and halt on breach.

### 6. Logging (`logger.py`)
Every signal is logged to SQLite — market question, Claude's score, market price, edge, side, amount, reasoning, and the headlines that informed the decision. Full audit trail.

---

## Architecture

```
scraper.py      News ingestion — RSS feeds + NewsAPI
markets.py      Polymarket market data — Gamma API + CLOB fallback
scorer.py       Claude confidence scoring engine
edge.py         Edge detection + Kelly criterion position sizing
executor.py     Trade execution — dry-run + live CLOB orders
logger.py       SQLite trade log + performance tracking
pipeline.py     Full pipeline orchestrator
dashboard.py    Live terminal dashboard (Bloomberg Terminal style)
cli.py          CLI interface — run, dashboard, verify, scrape, markets, trades, stats
config.py       All settings, thresholds, RSS sources
```

---

## Configuration

All settings live in `.env`:

| Setting | Default | What it does |
|---|---|---|
| `DRY_RUN` | `true` | Set to `false` for live trading |
| `MAX_BET_USD` | `25` | Maximum single bet size |
| `DAILY_LOSS_LIMIT_USD` | `100` | Pipeline halts if breached |
| `EDGE_THRESHOLD` | `0.10` | Minimum divergence to trigger a trade (10%) |

RSS feeds and market categories are configured in `config.py`.

---

## Safety

- **Dry-run mode is ON by default.** The pipeline logs everything but places zero real trades until you explicitly enable `--live`.
- **$25 max single bet.** Configurable, but you have to change it intentionally.
- **$100 daily loss limit.** Pipeline stops executing if you hit this.
- **Quarter-Kelly sizing.** Conservative position sizing that survives bad streaks.
- **API keys never leave your machine.** `.env` is gitignored. Nothing is sent anywhere except the APIs you configure.

---

## Requirements

- Python 3.9+
- Anthropic API key (for Claude confidence scoring)
- Polymarket account + API credentials (only for live trading — everything else works without it)

---

## What You Can Build From Here

This is a working foundation. Some ideas:

- **Add more news sources** — Reddit, Twitter/X API, Telegram channels, SEC filings
- **Smarter scoring** — feed Claude the full article text, not just headlines
- **Multi-model consensus** — score with Claude + GPT-4 + Gemini, only bet when all agree
- **Portfolio tracking** — monitor open positions, auto-exit when edge disappears
- **Cron job** — run the pipeline every hour automatically
- **Backtest engine** — score historical markets against historical news, measure calibration

---

Built by [@brodyautomates](https://github.com/brodyautomates)
