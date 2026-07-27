#!/usr/bin/env bash
# Verifica se ha commits novos no GitHub e dispara o deploy.
# Executado via cron a cada minuto. Sai silenciosamente se nao ha mudancas.
set -uo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/var/www/portal-passagens/venv/bin"

APP_DIR="/var/www/portal-passagens"
BRANCH="${DEPLOY_BRANCH:-main}"
LOCK="/tmp/portal-passagens-deploy.lock"

cd "$APP_DIR" || exit 1

# Evita execucoes simultaneas
if [ -f "$LOCK" ]; then
  exit 0
fi

git fetch --quiet origin "$BRANCH" 2>/dev/null || exit 0

LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null)

if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0
fi

touch "$LOCK"
/bin/bash "$APP_DIR/deploy.sh"
rm -f "$LOCK"
