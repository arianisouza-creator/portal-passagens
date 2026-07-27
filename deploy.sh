#!/usr/bin/env bash
# Auto-deploy do Portal Passagens (disparado pelo webhook do GitHub).
# Atualiza o codigo para origin/<branch>, reinstala dependencias se necessario
# e reinicia os servicos.
set -uo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/var/www/portal-passagens/venv/bin"

APP_DIR="/var/www/portal-passagens"
BRANCH="${DEPLOY_BRANCH:-main}"
LOG="$APP_DIR/deploy.log"

cd "$APP_DIR" || exit 1

{
  echo "===== deploy $(date -Is) ====="

  if ! git fetch --prune origin; then
    echo "ERRO: git fetch falhou"
    exit 1
  fi

  BEFORE="$(git rev-parse HEAD)"
  if ! git reset --hard "origin/$BRANCH"; then
    echo "ERRO: git reset falhou"
    exit 1
  fi
  AFTER="$(git rev-parse HEAD)"
  echo "before=$BEFORE after=$AFTER"

  if [ "$BEFORE" = "$AFTER" ]; then
    echo "Sem mudancas. Nada a fazer."
    exit 0
  fi

  if ! git diff --quiet "$BEFORE" "$AFTER" -- requirements.txt; then
    echo "requirements.txt mudou -> instalando dependencias"
    ./venv/bin/pip install -r requirements.txt
  fi

  echo "reiniciando portal-passagens.service"
  sudo systemctl restart portal-passagens.service

  if ! git diff --quiet "$BEFORE" "$AFTER" -- webhook.py; then
    echo "webhook.py mudou -> reiniciando webhook (detached)"
    sudo systemd-run --collect --quiet /usr/bin/systemctl restart portal-passagens-webhook.service || true
  fi

  echo "deploy concluido"
} >> "$LOG" 2>&1
