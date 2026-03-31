#!/bin/bash
# Polymarket Pipeline — One-Command Setup
# Usage: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "${GREEN}${BOLD}  POLYMARKET PIPELINE — SETUP${NC}"
echo -e "${GREEN}  News Scraper + AI Confidence Scorer + Auto Trader${NC}"
echo ""

# --- Check Python ---
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v $cmd &> /dev/null; then
        version=$($cmd --version 2>&1 | awk '{print $2}')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        patch=$(echo "$version" | cut -d. -f3)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON=$cmd
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}ERROR: Python 3.9+ is required.${NC}"
    echo "Install it with: brew install python@3.12"
    exit 1
fi

echo -e "${GREEN}✓${NC} Found $($PYTHON --version)"

# --- Create virtual environment ---
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    $PYTHON -m venv .venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${GREEN}✓${NC} Virtual environment exists"
fi

source .venv/bin/activate

# --- Install dependencies ---
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install --upgrade pip -q 2>/dev/null
pip install -r requirements.txt -q 2>/dev/null
echo -e "${GREEN}✓${NC} Dependencies installed"

# --- Setup .env ---
if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
else
    echo ""
    echo -e "${BOLD}Let's configure your API keys.${NC}"
    echo ""

    # Anthropic
    echo -e "${YELLOW}1. Anthropic API Key${NC} (required — get one at console.anthropic.com)"
    read -p "   Enter your Anthropic API key: " ANTHROPIC_KEY
    echo ""

    # Polymarket (optional)
    echo -e "${YELLOW}2. Polymarket API Credentials${NC} (optional — needed only for live trading)"
    read -p "   Enter Polymarket API key (or press Enter to skip): " POLY_KEY
    POLY_SECRET=""
    POLY_PASS=""
    POLY_PRIV=""
    if [ -n "$POLY_KEY" ]; then
        read -p "   Enter Polymarket API secret: " POLY_SECRET
        read -p "   Enter Polymarket API passphrase: " POLY_PASS
        read -p "   Enter Polymarket private key: " POLY_PRIV
    fi
    echo ""

    # NewsAPI (optional)
    echo -e "${YELLOW}3. NewsAPI Key${NC} (optional — broader news coverage, get one at newsapi.org)"
    read -p "   Enter NewsAPI key (or press Enter to skip): " NEWSAPI
    echo ""

    # Write .env
    cat > .env << ENVEOF
# Anthropic
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}

# Polymarket CLOB API
POLYMARKET_API_KEY=${POLY_KEY}
POLYMARKET_API_SECRET=${POLY_SECRET}
POLYMARKET_API_PASSPHRASE=${POLY_PASS}
POLYMARKET_PRIVATE_KEY=${POLY_PRIV}

# Optional: NewsAPI.org
NEWSAPI_KEY=${NEWSAPI}

# Pipeline Settings
DRY_RUN=true
MAX_BET_USD=25
DAILY_LOSS_LIMIT_USD=100
EDGE_THRESHOLD=0.10
ENVEOF

    echo -e "${GREEN}✓${NC} .env file created"
fi

# --- Verify ---
echo ""
echo -e "${YELLOW}Running verification...${NC}"
echo ""
$PYTHON cli.py verify

echo ""
echo -e "${GREEN}${BOLD}  SETUP COMPLETE${NC}"
echo ""
echo "  Next steps:"
echo "    source .venv/bin/activate"
echo "    python cli.py run              # Run the pipeline (dry-run)"
echo "    python cli.py dashboard        # Launch live dashboard"
echo "    python cli.py run --live       # Enable real trading"
echo ""
