#!/usr/bin/env bash
# ============================================================
# deploy.sh — PolyBot VPS Setup Script (Hostinger / Ubuntu)
#
# Usage:
#   1. SSH into your VPS
#   2. git clone https://github.com/lanchau633/polybot.git /opt/polybot
#   3. cd /opt/polybot && chmod +x deploy.sh && ./deploy.sh
#   4. Edit /opt/polybot/.env with your API keys
#   5. sudo systemctl start polybot
# ============================================================

set -euo pipefail

APP_DIR="/opt/polybot"
PYTHON_VERSION="3.11"

echo "=========================================="
echo "  PolyBot VPS Deployment"
echo "=========================================="

# --- 1. System packages ---
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python3-pip git

# --- 2. Create polybot user (if not exists) ---
echo "[2/6] Creating polybot user..."
if ! id -u polybot &>/dev/null; then
    sudo useradd -r -s /bin/false -d ${APP_DIR} polybot
fi
sudo chown -R polybot:polybot ${APP_DIR}

# --- 3. Python venv ---
echo "[3/6] Setting up Python virtual environment..."
if [ ! -d "${APP_DIR}/venv" ]; then
    python${PYTHON_VERSION} -m venv ${APP_DIR}/venv
fi
${APP_DIR}/venv/bin/pip install --upgrade pip -q
${APP_DIR}/venv/bin/pip install -r ${APP_DIR}/requirements.txt -q

echo "  To enable live trading, also run:"
echo "    ${APP_DIR}/venv/bin/pip install py-clob-client"

# --- 4. Environment file ---
echo "[4/6] Setting up .env..."
if [ ! -f "${APP_DIR}/.env" ]; then
    cp ${APP_DIR}/.env.example ${APP_DIR}/.env
    echo "  Created .env from template — EDIT IT with your API keys:"
    echo "    sudo nano ${APP_DIR}/.env"
else
    echo "  .env already exists — skipping"
fi
sudo chmod 600 ${APP_DIR}/.env
sudo chown polybot:polybot ${APP_DIR}/.env

# --- 5. Install systemd service ---
echo "[5/6] Installing systemd service..."
sudo cp ${APP_DIR}/polybot.service /etc/systemd/system/polybot.service
sudo systemctl daemon-reload
sudo systemctl enable polybot

# --- 6. Verify ---
echo "[6/6] Verifying installation..."
${APP_DIR}/venv/bin/python -c "import config; print(f'  DRY_RUN={config.DRY_RUN}')"
${APP_DIR}/venv/bin/python -c "import sports_scanner; print('  sports_scanner: OK')"
${APP_DIR}/venv/bin/python -c "import notifier; print('  notifier: OK')"
${APP_DIR}/venv/bin/python -c "import edge_detector; print('  edge_detector: OK')"
${APP_DIR}/venv/bin/python -c "import risk_manager; print('  risk_manager: OK')"
${APP_DIR}/venv/bin/python -c "import stop_loss_monitor; print('  stop_loss_monitor: OK')"
${APP_DIR}/venv/bin/python -c "import daily_report; print('  daily_report: OK')"

echo ""
echo "=========================================="
echo "  Deployment complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit your API keys:  sudo nano ${APP_DIR}/.env"
echo "  2. Run smoke tests:     cd ${APP_DIR} && ${APP_DIR}/venv/bin/python test_phase1.py"
echo "  3. Start the bot:       sudo systemctl start polybot"
echo "  4. Check logs:          journalctl -u polybot -f"
echo "  5. Stop the bot:        sudo systemctl stop polybot"
echo ""
echo "  DRY_RUN is ON by default — no real trades until you change it."
echo ""
