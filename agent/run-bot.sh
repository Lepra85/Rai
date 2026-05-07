#!/bin/bash
# Run the Telegram bot in the foreground (for testing).
# For background, use: sudo systemctl start rai-bot
set -e
cd "$(dirname "$0")"

git pull --quiet origin agent 2>/dev/null || true

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet -r requirements.txt

source .venv/bin/activate
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
python bot.py
