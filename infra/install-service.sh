#!/bin/bash
# Install the Rai domain service on the droplet that already runs the
# Telegram bot. Idempotent: safe to re-run after every push.
#
# Run as root from anywhere on the droplet:
#   sudo bash /home/rai/repo/infra/install-service.sh
#
# Prerequisites (provisioned out-of-band before first run):
#   /home/rai/repo/service/.env  with DATABASE_URL, FLOW_API_SECRET, KAPSO_API_KEY.
#   Copy your local service/.env.example to the droplet and fill it in:
#     scp service/.env root@<droplet-ip>:/home/rai/repo/service/.env
#     ssh root@<droplet-ip> chown rai:rai /home/rai/repo/service/.env
#     ssh root@<droplet-ip> chmod 600 /home/rai/repo/service/.env
set -euo pipefail

REPO_DIR=/home/rai/repo
SERVICE_DIR=$REPO_DIR/service
ENV_FILE=$SERVICE_DIR/.env
UNIT_SRC=$REPO_DIR/infra/systemd/rai-service.service
UNIT_DST=/etc/systemd/system/rai-service.service
CADDY_SRC=$REPO_DIR/infra/Caddyfile
CADDY_DST=/etc/caddy/Caddyfile
HOSTNAME=raiagent.duckdns.org

if [[ $EUID -ne 0 ]]; then
	echo "ERROR: run as root (sudo)" >&2
	exit 1
fi

if [[ ! -d $REPO_DIR ]]; then
	echo "ERROR: $REPO_DIR does not exist (cloud-init incomplete?)" >&2
	exit 1
fi

echo "[1/8] Pulling latest code from origin/main"
sudo -u rai git -C "$REPO_DIR" fetch --quiet origin main
sudo -u rai git -C "$REPO_DIR" checkout --quiet main
sudo -u rai git -C "$REPO_DIR" pull --quiet --ff-only origin main

echo "[2/8] Verifying $ENV_FILE"
if [[ ! -f $ENV_FILE ]]; then
	echo "ERROR: $ENV_FILE not found." >&2
	echo "Copy your service/.env to the droplet first:" >&2
	echo "  scp service/.env root@<droplet-ip>:$ENV_FILE" >&2
	exit 1
fi
for key in DATABASE_URL FLOW_API_SECRET; do
	if ! grep -q "^${key}=." "$ENV_FILE"; then
		echo "ERROR: $key is empty in $ENV_FILE" >&2
		exit 1
	fi
done

echo "[3/8] Installing Python deps in service/.venv"
sudo -u rai bash -lc "cd $SERVICE_DIR && [ -d .venv ] || python3 -m venv .venv"
sudo -u rai bash -lc "cd $SERVICE_DIR && .venv/bin/pip install -q --upgrade pip"
sudo -u rai bash -lc "cd $SERVICE_DIR && .venv/bin/pip install -q -e ."

echo "[4/8] Running Alembic migrations (idempotent)"
sudo -u rai bash -lc "cd $SERVICE_DIR && .venv/bin/alembic upgrade head"

echo "[5/8] Installing systemd unit rai-service.service"
install -m 644 "$UNIT_SRC" "$UNIT_DST"
touch /var/log/rai-service.log
chown rai:rai /var/log/rai-service.log
systemctl daemon-reload
systemctl enable --now rai-service.service
systemctl restart rai-service.service

echo "[6/8] Installing Caddy (apt) if missing"
if ! command -v caddy >/dev/null 2>&1; then
	apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
	apt-get update -qq
	apt-get install -y caddy
fi

echo "[7/8] Installing Caddyfile and opening ports 80/443"
install -m 644 "$CADDY_SRC" "$CADDY_DST"
mkdir -p /var/log/caddy
chown caddy:caddy /var/log/caddy 2>/dev/null || true
if command -v ufw >/dev/null 2>&1; then
	ufw allow 80/tcp  >/dev/null 2>&1 || true
	ufw allow 443/tcp >/dev/null 2>&1 || true
fi
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "[8/8] Smoke test"
sleep 2
if curl -fsS "http://127.0.0.1:8000/healthz" >/dev/null; then
	echo "  local uvicorn /healthz OK"
else
	echo "  WARN: uvicorn /healthz did not respond — check journalctl -u rai-service" >&2
fi

echo
echo "Done. Public URL: https://${HOSTNAME}"
echo
echo "Try from your laptop:"
echo "  curl https://${HOSTNAME}/healthz"
echo
echo "First HTTPS request may take 10-30s while Caddy fetches the LE cert."
echo "Logs:"
echo "  journalctl -u rai-service -f"
echo "  journalctl -u caddy -f"
