#!/bin/bash
# Install the Rai Telegram bot on a freshly cloud-init'ed droplet.
# Idempotent: safe to re-run.
#
# Run as root from anywhere on the droplet:
#   sudo bash /home/rai/repo/infra/install-bot.sh
#
# Will prompt for TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS unless
# they're already in /home/rai/repo/agent/.env. OPENAI_API_KEY is expected
# to already be there (set by cloud-init).
set -euo pipefail

REPO_DIR=/home/rai/repo
AGENT_DIR=$REPO_DIR/agent
ENV_FILE=$AGENT_DIR/.env
UNIT_SRC=$REPO_DIR/infra/systemd/rai-bot.service
UNIT_DST=/etc/systemd/system/rai-bot.service

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo)" >&2
  exit 1
fi

if [[ ! -d $REPO_DIR ]]; then
  echo "ERROR: $REPO_DIR does not exist (cloud-init incomplete?)" >&2
  exit 1
fi

echo "[1/5] Pulling latest code from origin/main"
sudo -u rai git -C "$REPO_DIR" fetch --quiet origin main
sudo -u rai git -C "$REPO_DIR" checkout --quiet main
sudo -u rai git -C "$REPO_DIR" pull --quiet --ff-only origin main

echo "[2/5] Installing/updating Python deps"
sudo -u rai bash -lc "cd $AGENT_DIR && [ -d .venv ] || python3 -m venv .venv"
sudo -u rai bash -lc "cd $AGENT_DIR && .venv/bin/pip install -q --upgrade pip"
sudo -u rai bash -lc "cd $AGENT_DIR && .venv/bin/pip install -q -r requirements.txt"

echo "[3/5] Configuring .env"
if [[ ! -f $ENV_FILE ]]; then
  echo "ERROR: $ENV_FILE not found (cloud-init should have created it)" >&2
  exit 1
fi

if ! grep -q '^TELEGRAM_BOT_TOKEN=.' "$ENV_FILE"; then
  read -r -s -p "Pegá TELEGRAM_BOT_TOKEN (no se muestra): " TG_TOKEN
  echo
  if [[ -z "$TG_TOKEN" ]]; then
    echo "ERROR: token vacío" >&2
    exit 1
  fi
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TG_TOKEN" >> "$ENV_FILE"
  unset TG_TOKEN
  echo "  TELEGRAM_BOT_TOKEN guardado"
else
  echo "  TELEGRAM_BOT_TOKEN ya estaba"
fi

if ! grep -q '^TELEGRAM_ALLOWED_CHAT_IDS=.' "$ENV_FILE"; then
  read -r -p "Pegá TELEGRAM_ALLOWED_CHAT_IDS (coma-separados): " TG_CHATS
  if [[ -z "$TG_CHATS" ]]; then
    echo "ERROR: chat_ids vacío" >&2
    exit 1
  fi
  printf 'TELEGRAM_ALLOWED_CHAT_IDS=%s\n' "$TG_CHATS" >> "$ENV_FILE"
  echo "  TELEGRAM_ALLOWED_CHAT_IDS guardado"
else
  echo "  TELEGRAM_ALLOWED_CHAT_IDS ya estaba"
fi

chown rai:rai "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "[4/5] Installing systemd unit"
cp "$UNIT_SRC" "$UNIT_DST"
touch /var/log/rai-bot.log
chown rai:rai /var/log/rai-bot.log
systemctl daemon-reload

echo "[5/5] Starting rai-bot"
systemctl enable --now rai-bot
sleep 3
systemctl status rai-bot --no-pager | head -12 || true

echo
echo "✅ Listo. Logs:  sudo journalctl -u rai-bot -f"
