"""Portal-MSE - servidor único Flask.

Serve o portal (controle-internet.html) e expõe uma API REST mínima,
compatível com o formato que o front-end já usava com o Supabase/PostgREST,
mas apontando agora para um banco MySQL.

Endpoints:
  GET    /                      -> portal HTML com a config injetada
  GET    /health                -> healthcheck (inclui teste de conexão ao banco)
  GET    /rest/v1/<table>       -> SELECT * (com ?select=*&order=col.asc,...)
  POST   /rest/v1/<table>       -> upsert (INSERT ... ON DUPLICATE KEY UPDATE)
  DELETE /rest/v1/<table>       -> DELETE com filtro (?coluna=eq.valor)

Configuração via variáveis de ambiente (ver .env.example):
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
  PASSAGENS_API_BASE_URL, PASSAGENS_API_TOKEN
  PORTAL_API_BASE_URL (base da API usada pelo front; vazio = mesma origem)
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymysql
from flask import Flask, Response, abort, g, jsonify, request
from pymysql.cursors import DictCursor

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv é opcional
    pass


BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "controle-internet.html"
PROJECT_CONFIG_FILE = BASE_DIR / "project-config.json"
def _clean(value: str) -> str:
    return (value or "").strip()
PASSAGENS_SEED_FILE = Path(__file__).with_name("passagens-import-seed.json")

DEFAULT_PROJECT_CONFIG = {
    "key": "internet",
    "name": "Portal Internet",
    "browserTitle": "MSE | Portal Internet",
    "brandTitle": "Portal Internet",
    "brandSubtitle": "Controle administrativo · operacao mensal",
    "greeting": "Boa tarde. Bem-vinda ao Portal Internet.",
    "defaultModule": "internet",
    "enabledModules": ["internet"],
}


def load_optional_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_project_config() -> dict:
    raw = load_optional_json(PROJECT_CONFIG_FILE)
    merged = {**DEFAULT_PROJECT_CONFIG}
    if isinstance(raw, dict):
        merged.update({key: value for key, value in raw.items() if value is not None})
    enabled_modules = merged.get("enabledModules")
    if not isinstance(enabled_modules, list) or not enabled_modules:
        merged["enabledModules"] = list(DEFAULT_PROJECT_CONFIG["enabledModules"])
    default_module = _clean(str(merged.get("defaultModule", "")))
    if default_module not in merged["enabledModules"]:
        merged["defaultModule"] = merged["enabledModules"][0]
    return merged


DB_CONFIG = {
    "host": _clean(os.getenv("DB_HOST", "dbsubdominios.portalmse.com.br")),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": _clean(os.getenv("DB_USER", "controle_internet_prod")),
    "password": os.getenv("DB_PASSWORD", "controle_internet@2026"),
    "database": _clean(os.getenv("DB_NAME", "controle_internet")),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "autocommit": True,
    "connect_timeout": 10,
}


# Whitelist de tabelas e colunas. Impede SQL injection nos nomes de
# tabela/coluna e nas cláusulas ORDER BY / WHERE montadas dinamicamente.
TABLES: dict[str, dict] = {
    "internet_contracts": {
        "columns": [
            "id", "empresa", "obra", "vencimento", "numero_contrato",
            "status_contrato", "inicio_contrato", "fim_contrato", "contato",
            "obs_contrato", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "internet_month_entries": {
        "columns": [
            "month_key", "contract_id", "status", "valor", "pedido",
            "aprovado", "s1", "login_acesso", "senha_acesso", "obs",
            "created_at",
        ],
        "json": [],
        "bool": ["aprovado", "s1"],
    },
    "internet_lines": {
        "columns": [
            "id", "month_key", "numero", "responsavel", "status",
            "centro_custo", "percentual", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "diarista_cadastros": {
        "columns": [
            "id", "obra_diarista", "nome_diarista", "status_diarista",
            "inicio_diarista", "fim_diarista", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "diarista_month_entries": {
        "columns": [
            "month_key", "diarista_id", "pedido", "valor", "protocolado",
            "link", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "hitachi_collaborators": {
        "columns": [
            "id", "month_key", "empresa", "colaborador", "situacao",
            "holerite", "comprovante_pagamento", "comprovante_adiantamento",
            "kit_rescisao", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "hitachi_company_docs": {
        "columns": [
            "id", "month_key", "empresa", "documento", "status", "created_at",
        ],
        "json": [],
        "bool": [],
    },
    "passagens_rows": {
        "columns": ["key", "tabela", "item", "updated_at"],
        "json": ["item"],
        "bool": [],
    },
    "passagens_complements": {
        "columns": ["key", "data", "updated_at"],
        "json": ["data"],
        "bool": [],
    },
    "passagens_creditos": {
        "columns": ["id", "data", "updated_at"],
        "json": ["data"],
        "bool": [],
    },
}


app = Flask(__name__)
# alias usado por alguns servidores de produção (ex.: Elastic Beanstalk).
application = app


# --------------------------------------------------------------------------- #
# Conexão MySQL (uma conexão por requisição, fechada no teardown).
# --------------------------------------------------------------------------- #
def get_db() -> pymysql.connections.Connection:
    if "db" not in g:
        g.db = pymysql.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Config injetada no HTML.
# --------------------------------------------------------------------------- #
def load_portal_config() -> dict:
    return {
        "project": load_project_config(),
        "api": {
            # vazio => mesma origem: as chamadas viram /rest/v1/<tabela>.
            "baseUrl": _clean(os.getenv("PORTAL_API_BASE_URL", "")),
            "enabled": True,
        },
        "passagens": {
            "baseUrl": _clean(
                os.getenv(
                    "PASSAGENS_API_BASE_URL",
                    "https://portalmse.com.br/microservices/hub_mse/api_passagens",
                )
            ),
            "token": _clean(os.getenv("PASSAGENS_API_TOKEN", "")),
            "useApiOnly": True,
        },
        "passagensSeed": load_optional_json(PASSAGENS_SEED_FILE),
    }


def render_portal() -> str:
    if not HTML_FILE.exists():
        abort(500, f"Arquivo não encontrado: {HTML_FILE}")
    html = HTML_FILE.read_text(encoding="utf-8")
    config_json = json.dumps(load_portal_config()).replace("</", "<\\/")
    injection = f"<script>window.PORTAL_CONFIG = {config_json};</script>"
    if "</head>" in html:
        return html.replace("</head>", f"  {injection}\n</head>", 1)
    return f"{injection}\n{html}"


# --------------------------------------------------------------------------- #
# Serialização de linhas vindas do MySQL.
# --------------------------------------------------------------------------- #
def serialize_row(table: str, row: dict) -> dict:
    meta = TABLES[table]
    out: dict = {}
    for key, value in row.items():
        if value is None:
            out[key] = None
        elif key in meta["json"]:
            out[key] = json.loads(value) if isinstance(value, (str, bytes)) else value
        elif key in meta["bool"]:
            out[key] = bool(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def encode_value(table: str, column: str, value):
    """Prepara o valor de uma coluna para INSERT/UPDATE."""
    if column in TABLES[table]["json"]:
        return json.dumps(value if value is not None else {})
    return value


# --------------------------------------------------------------------------- #
# Rotas do portal.
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> Response:
    return Response(render_portal(), mimetype="text/html")


@app.get("/health")
def health():
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return jsonify({"status": "ok", "database": DB_CONFIG["database"]})
    except Exception as exc:  # pragma: no cover - diagnóstico
        return jsonify({"status": "error", "detail": str(exc)}), 500


# --------------------------------------------------------------------------- #
# API REST (subconjunto compatível com o front antigo).
# --------------------------------------------------------------------------- #
def _validate_table(table: str) -> dict:
    meta = TABLES.get(table)
    if meta is None:
        abort(404, f"Tabela desconhecida: {table}")
    return meta


def _build_order(table: str, order_param: str) -> str:
    meta = TABLES[table]
    parts = []
    for chunk in order_param.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        column, _, direction = chunk.partition(".")
        if column not in meta["columns"]:
            abort(400, f"Coluna inválida em order: {column}")
        direction = "DESC" if direction.lower() == "desc" else "ASC"
        parts.append(f"`{column}` {direction}")
    return ", ".join(parts)


def _build_filters(table: str) -> tuple[str, list]:
    """Interpreta filtros no formato PostgREST simples: coluna=eq.valor."""
    meta = TABLES[table]
    clauses: list[str] = []
    values: list = []
    for column, raw in request.args.items():
        if column in ("select", "order"):
            continue
        if column not in meta["columns"]:
            abort(400, f"Coluna inválida em filtro: {column}")
        operator, _, val = raw.partition(".")
        if operator != "eq":
            abort(400, f"Operador não suportado: {operator}")
        clauses.append(f"`{column}` = %s")
        values.append(val)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, values


@app.route("/rest/v1/<table>", methods=["GET", "POST", "DELETE", "OPTIONS"])
def rest(table: str):
    if request.method == "OPTIONS":
        return ("", 204)

    meta = _validate_table(table)
    db = get_db()

    if request.method == "GET":
        where, values = _build_filters(table)
        order = request.args.get("order", "")
        sql = f"SELECT * FROM `{table}`{where}"
        if order:
            sql += f" ORDER BY {_build_order(table, order)}"
        with db.cursor() as cur:
            cur.execute(sql, values)
            rows = cur.fetchall()
        return jsonify([serialize_row(table, row) for row in rows])

    if request.method == "DELETE":
        where, values = _build_filters(table)
        if not where:
            abort(400, "DELETE sem filtro não é permitido.")
        with db.cursor() as cur:
            cur.execute(f"DELETE FROM `{table}`{where}", values)
        return ("", 204)

    # POST -> upsert (aceita objeto único ou lista de objetos)
    payload = request.get_json(silent=True)
    if payload is None:
        abort(400, "Corpo JSON inválido.")
    rows = payload if isinstance(payload, list) else [payload]

    with db.cursor() as cur:
        for row in rows:
            columns = [c for c in row.keys() if c in meta["columns"]]
            if not columns:
                abort(400, "Nenhuma coluna válida no corpo.")
            placeholders = ", ".join(["%s"] * len(columns))
            col_sql = ", ".join(f"`{c}`" for c in columns)
            updates = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in columns)
            sql = (
                f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
            cur.execute(sql, [encode_value(table, c, row[c]) for c in columns])

    prefer = request.headers.get("Prefer", "")
    if "return=representation" in prefer:
        return jsonify(rows), 201
    return ("", 201)


@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault(
        "Access-Control-Allow-Headers", "Content-Type, Prefer, apikey, Authorization"
    )
    response.headers.setdefault(
        "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
    )
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
