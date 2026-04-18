#!/bin/bash
# ─── BrightHaven Cloud IoT Platform — Launch Script ──────────────────────────
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   BrightHaven Cloud IoT Platform     ║"
echo "║           v2.0 Launcher              ║"
echo "╚══════════════════════════════════════╝"

# ── 1. Load .env file if exists ───────────────────────────────────────────────
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "✓ Environment loaded from .env"
else
    echo "⚠ No .env file found — using defaults"
    export FLASK_SECRET_KEY="brighthaven_2026_mk_secure"
    export BLYNK_TOKEN="B5a6tgOxySyna1GKlB3k_ZKhhJefttXM"
fi

export FLASK_APP=app.py

# ── 2. Install dependencies only if missing ───────────────────────────────────
install_if_missing() {
    python3 -c "import $1" 2>/dev/null || {
        echo "Installing $2..."
        pip3 install $2 --break-system-packages -q 2>/dev/null || pip install $2 -q
    }
}

install_if_missing flask         flask
install_if_missing firebase_admin firebase-admin
install_if_missing requests      requests
install_if_missing gunicorn      gunicorn
install_if_missing dotenv        python-dotenv

# Optional but recommended
python3 -c "import paho.mqtt.client" 2>/dev/null || {
    echo "Installing paho-mqtt (MQTT support)..."
    pip3 install paho-mqtt --break-system-packages -q 2>/dev/null || pip install paho-mqtt -q
}

echo "✓ Dependencies ready"

# ── 3. Kill existing BrightHaven process & find port ──────────────────────────
fuser -k 5000/tcp 2>/dev/null && echo "✓ Freed port 5000" && sleep 1
PORT=5000
while lsof -Pi :$PORT -sTCP:LISTEN -t &>/dev/null 2>&1; do
    PORT=$((PORT + 1))
done
export FLASK_PORT=$PORT

# ── 4. Network info ──────────────────────────────────────────────────────────
CURRENT_IP=$(ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
[ -z "$CURRENT_IP" ] && CURRENT_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "  Local:   http://127.0.0.1:$PORT"
[ -n "$CURRENT_IP" ] && echo "  Network: http://$CURRENT_IP:$PORT"
echo ""

# ── 5. MQTT Broker check ─────────────────────────────────────────────────────
MQTT_BROKER=${MQTT_BROKER:-"broker.emqx.io"}
echo "  MQTT:    $MQTT_BROKER"
echo ""

# ── 6. Open browser after 3s ─────────────────────────────────────────────────
(sleep 3 && (xdg-open "http://127.0.0.1:$PORT" || google-chrome "http://127.0.0.1:$PORT") &>/dev/null &) &

# ── 7. Run with Gunicorn (production) or Flask (dev) ─────────────────────────
if command -v gunicorn &>/dev/null; then
    echo "Starting with Gunicorn (production mode)..."
    exec gunicorn app:app \
        --bind 0.0.0.0:$PORT \
        --workers 2 \
        --threads 4 \
        --worker-class gthread \
        --timeout 30 \
        --keep-alive 5 \
        --access-logfile - \
        --error-logfile flask_error.log \
        --preload \
        2>&1
else
    echo "Starting with Flask (dev mode) on port $PORT..."
    python3 app.py 2>&1 | tee flask_error.log
fi