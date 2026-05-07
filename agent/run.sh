#!/bin/bash
# Helper to run the agent on the droplet.
# Usage: ./run.sh
set -e
cd "$(dirname "$0")"

# Pull latest code (skip if no internet/repo issue)
git pull --quiet origin agent 2>/dev/null || true

# Activate venv
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
source .venv/bin/activate

# Load .env into environment
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

python agent.py
