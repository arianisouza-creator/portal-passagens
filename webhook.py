"""Listener de webhook do GitHub para auto-deploy do Portal-MSE.

Roda como um serviço separado (systemd -> gunicorn em 127.0.0.1:5061), atrás do
mesmo Nginx do portal, no path /gh-deploy. Ao receber um push válido na branch de
produção, dispara o deploy.sh de forma destacada.

Fica em serviço próprio (portal-mse-webhook.service) justamente para NÃO ser
derrubado quando o deploy reinicia o portal-mse.service.

Validação de segurança: assinatura HMAC-SHA256 do GitHub
(header X-Hub-Signature-256) usando o segredo GITHUB_WEBHOOK_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
from pathlib import Path

from flask import Flask, abort, jsonify, request

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent
DEPLOY_SCRIPT = str(BASE_DIR / "deploy.sh")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
DEPLOY_BRANCH = os.getenv("DEPLOY_BRANCH", "main").strip()

app = Flask(__name__)


def _valid_signature(raw: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET or not signature:
        return False
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/gh-deploy")
def gh_deploy_health():
    return jsonify({"service": "portal-mse-webhook", "status": "ok"})


@app.post("/gh-deploy")
def gh_deploy():
    if not WEBHOOK_SECRET:
        abort(503, "GITHUB_WEBHOOK_SECRET nao configurado")

    raw = request.get_data()
    if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        abort(403, "assinatura invalida")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return jsonify({"msg": "pong"})
    if event != "push":
        return jsonify({"ignored_event": event})

    payload = request.get_json(silent=True) or {}
    ref = payload.get("ref", "")
    if ref != f"refs/heads/{DEPLOY_BRANCH}":
        return jsonify({"ignored_ref": ref})

    # Deploy destacado: sobrevive ao restart do portal-mse.service.
    subprocess.Popen(
        ["/bin/bash", DEPLOY_SCRIPT],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return jsonify({"status": "deploy iniciado", "ref": ref})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("WEBHOOK_PORT", "5061")))
