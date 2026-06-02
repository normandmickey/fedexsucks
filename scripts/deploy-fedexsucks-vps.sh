#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-docstore-vps}"
REMOTE_DIR="${REMOTE_DIR:-/home/norm/sites/fedexsucks}"
BRANCH="${BRANCH:-main}"
APP_NAME="${APP_NAME:-fedexsucks}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PIP_BIN="${PIP_BIN:-.venv/bin/pip}"

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.env' \
  --exclude 'db.sqlite3' \
  ./ "$REMOTE_HOST:$REMOTE_DIR/"

ssh "$REMOTE_HOST" "
  set -euo pipefail
  cd '$REMOTE_DIR'
  python3 -m venv .venv
  $PIP_BIN install --upgrade pip
  $PIP_BIN install -r requirements.txt
  if [ -f .env ]; then
    set -a
    . ./.env
    set +a
  fi
  $PYTHON_BIN manage.py migrate
  $PYTHON_BIN manage.py collectstatic --noinput
  sudo systemctl restart ${APP_NAME}.service || true
  sudo systemctl is-active ${APP_NAME}.service || true
"

echo "[deploy-fedexsucks] deploy complete"
