#!/bin/bash
# Runs on the droplet via cloud-init.
# Installs Node.js, Claude Code, Bun, sets up bot venv, enables systemd unit.
set -euxo pipefail
exec > >(tee -a /var/log/rai-setup.log) 2>&1
echo "=== Rai setup START $(date -u) ==="

# --- Node.js 20 LTS (NodeSource) ---
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
node -v
npm -v

# --- Claude Code (global) ---
npm install -g @anthropic-ai/claude-code
which claude
claude --version || true

# --- Bun for the rai user ---
sudo -u rai bash -lc 'curl -fsSL https://bun.sh/install | bash' || true

# --- Bot Python venv ---
cd /opt/rai/bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# --- Permissions ---
mkdir -p /home/rai/.rai /home/rai/.claude
chown -R rai:rai /opt/rai /home/rai/.rai /home/rai/.claude

# --- Bot log file ---
touch /var/log/rai-bot.log
chown rai:rai /var/log/rai-bot.log

# --- Enable (do not start) the bot ---
systemctl daemon-reload
systemctl enable rai-bot.service

# --- Marker ---
touch /var/log/rai-setup-done
echo "=== Rai setup DONE $(date -u) ==="
