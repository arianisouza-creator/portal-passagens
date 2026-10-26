"""Módulo Cotação de passagens (aba "Cotação" do Portal Passagens).

Busca voos no Google Flights via SerpApi, mostra só o preço direto da companhia aérea,
exige justificativa quando a pessoa não escolhe o menor preço e registra a solicitação.

Uso (em app.py, depois do load_dotenv e de definir get_db):
    from cotacao import init_cotacao
    init_cotacao(app, get_db)

Rotas (todas sob /cotacao): /, /solicitacoes, /api/cidades, /api/buscar, /api/solicitar, /uploads/<arquivo>.
Banco: usa o mesmo MySQL do portal (tabelas cotacao_buscas e cotacao_solicitacoes, criadas sozinhas).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps

from flask import (Blueprint, Response, abort, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)

from .cidades import CIDADES

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(os.path.dirname(BASE), "uploads", "cotacao")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()
FORCAR_EXEMPLO = os.environ.get("MODO_EXEMPLO", "") == "1"
ADMIN_PASSWORD = os.environ.get("COTACAO_ADMIN_PASSWORD", "")
CACHE_MINUTOS = 30          # reaproveita busca idêntica (economiza créditos)
MAX_RESULTADOS = 60         # teto de voos lidos por trecho (praticamente tudo que o Google devolve)
MIN_JUSTIFICATIVA = 10      # caracteres
# Quantas opções (das mais baratas no Google) têm o preço DIRETO NA COMPANHIA conferido por trecho.
# Cada conferência gasta 1 crédito do SerpApi. Padrão: confere TODAS (até 30). Ajuste no .env (OPCOES_COMPANHIA=30).
OPCOES_COMPANHIA = max(1, min(60, int(os.environ.get("OPCOES_COMPANHIA", "30") or 30)))

bp = Blueprint("cotacao", __name__, url_prefix="/cotacao", template_folder="templates",
               static_folder="static", static_url_path="/static")

_get_db = None


def modo_busca():
    return "serpapi" if (SERPAPI_KEY and not FORCAR_EXEMPLO) else "exemplo"


# --------------------------------------------------------------------------- banco (MySQL do portal)
DDL = [
    "CREATE TABLE IF NOT EXISTS cotacao_buscas ("
    " id VARCHAR(32) NOT NULL, chave VARCHAR(64) NOT NULL, criado_em VARCHAR(25) NOT NULL,"
    " modo VARCHAR(16) NOT NULL, params_json LONGTEXT NOT NULL, ida_json LONGTEXT NOT NULL, volta_json LONGTEXT NOT NULL,"
    " PRIMARY KEY (id), KEY ix_cotacao_buscas_chave (chave, criado_em)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci",
    "CREATE TABLE IF NOT EXISTS cotacao_solicitacoes ("
    " id INT NOT NULL AUTO_INCREMENT, criado_em VARCHAR(25) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'Nova',"
    " dados_json LONGTEXT NOT NULL, busca_id VARCHAR(32) NULL, escolha_ida VARCHAR(32) NULL, escolha_volta VARCHAR(32) NULL,"
    " melhor_preco_ok TINYINT NULL, justificativa TEXT NULL, preco_escolhido DECIMAL(12,2) NULL,"
    " preco_melhor DECIMAL(12,2) NULL, documento VARCHAR(80) NULL,"
    " PRIMARY KEY (id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci",
]
_tabelas_ok = False


def _db():
    global _tabelas_ok
    con = _get_db()
    if not _tabelas_ok:
        with con.cursor() as cur:
            for ddl in DDL:
                cur.execute(ddl)
        _tabelas_ok = True
    return con


def _limpa(row):
    if row is None:
        return None
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()}


def q_um(sql, params=()):
    with _db().cursor() as cur:
        cur.execute(sql, params)
        return _limpa(cur.fetchone())


def q_todos(sql, params=()):
    with _db().cursor() as cur:
        cur.execute(sql, params)
        return [_limpa(r) for r in cur.fetchall()]


def q_exec(sql, params=()):
    """Executa INSERT/UPDATE e devolve o id gerado (se houver)."""
    with _db().cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def init_cotacao(app, get_db):
    """Registra o módulo no app Flask do portal. get_db() deve devolver a conexão pymysql (DictCursor)."""
    global _get_db
    _get_db = get_db
    os.makedirs(UPLOADS, exist_ok=True)
    app.register_blueprint(bp)


# --------------------------------------------------------------------------- SerpApi
class BuscaErro(Exception):
    pass


def _mascarar(txt):
    return txt.replace(SERPAPI_KEY, "***") if SERPAPI_KEY else txt


def normalizar_serpapi(d):
    """Converte a resposta do engine google_flights numa lista simples de ofertas."""
    brutos = (d.get("best_flights") or []) + (d.get("other_flights") or [])
    saida, vistos = [], set()
    for r in brutos:
        segs = r.get("flights") or []
        preco = r.get("price")
        if not segs or not isinstance(preco, (int, float)):
            continue
        segmentos = []
        for s in segs:
            dep, arr = s.get("departure_airport", {}), s.get("arrival_airport", {})
            segmentos.append({
                "cia": s.get("airline", ""),
                "numero": s.get("flight_number", ""),
                "dep_id": dep.get("id", ""), "dep_nome": dep.get("name", ""), "dep_hora": dep.get("time", ""),
                "arr_id": arr.get("id", ""), "arr_nome": arr.get("name", ""), "arr_hora": arr.get("time", ""),
            })
        oid = hashlib.sha1("|".join(f"{s['numero']}@{s['dep_hora']}" for s in segmentos).encode()).hexdigest()[:12]
        if oid in vistos:
            continue
        vistos.add(oid)
        duracao = r.get("total_duration") or sum(int(s.get("duration") or 0) for s in segs)
        saida.append({
            "id": oid,
            "preco": float(preco),            # será trocado pelo preço na companhia
            "preco_google": float(preco),     # menor preço entre todos os vendedores (agências inclusas)
            "booking_token": r.get("booking_token"),
            "cias": sorted({s["cia"] for s in segmentos if s["cia"]}),
            "segmentos": segmentos,
            "origem_id": segmentos[0]["dep_id"],
            "destino_id": segmentos[-1]["arr_id"],
            "partida": segmentos[0]["dep_hora"],
            "chegada": segmentos[-1]["arr_hora"],
            "duracao_min": int(duracao or 0),
            "escalas": len(segmentos) - 1,
            "escalas_em": [l.get("id", "") for l in (r.get("layovers") or [])],
            "exemplo": False,
        })
    saida.sort(key=lambda o: (o["preco"], o["duracao_min"]))
    return saida[:MAX_RESULTADOS]


def _serpapi_get(q):
    """Uma chamada ao SerpApi. Devolve o JSON ou levanta BuscaErro (com a chave mascarada)."""
    q = dict(q, api_key=SERPAPI_KEY)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "ignore")
        try:
            msg = json.loads(corpo).get("error", corpo)
        except ValueError:
            msg = corpo
        raise BuscaErro(_mascarar(f"SerpApi respondeu {e.code}: {msg[:200]}"))
    except Exception as e:  # rede, timeout...
        raise BuscaErro(_mascarar("Não consegui falar com o SerpApi: " + str(e)))


def _sem_resultado(erro):
    return "hasn't returned any results" in erro or "no results" in erro.lower()


def _nome_bate(vendedor, cias):
    v = re.sub(r"[^a-z0-9]", "", (vendedor or "").lower())
    return any(v and (v in c or c in v) for c in (re.sub(r"[^a-z0-9]", "", x.lower()) for x in cias) if c)


def extrair_preco_companhia(d, cias):
    """Do JSON de 'booking options', devolve a MENOR opção vendida pela própria companhia, ou None.

    Cada item de booking_options tem um bloco "together" com book_with (quem vende), price e,
    quando quem vende é a companhia aérea, airline=true. Se o campo airline não vier, comparo
    o nome do vendedor com o nome das companhias do voo.
    """
    melhores = []
    for bo in d.get("booking_options") or []:
        t = bo.get("together") or {}
        preco = t.get("price")
        if not isinstance(preco, (int, float)):
            continue
        eh_cia = t["airline"] is True if "airline" in t else _nome_bate(t.get("book_with"), cias)
        if eh_cia:
            melhores.append({"preco": float(preco), "vendedor": t.get("book_with", ""),
                             "tarifa": t.get("option_title", ""),
                             "bagagem": "; ".join(str(x) for x in (t.get("baggage_prices") or []))[:160]})
    return min(melhores, key=lambda m: m["preco"]) if melhores else None


def _preco_companhia(o, data_iso):
    q = dict(engine="google_flights", departure_id=o["origem_id"], arrival_id=o["destino_id"],
             outbound_date=(o["partida"] or data_iso)[:10], type="2", currency="BRL", hl="pt", gl="br",
             booking_token=o["booking_token"])
    d = _serpapi_get(q)
    if d.get("error"):
        raise BuscaErro(_mascarar("SerpApi: " + str(d["error"])))
    return extrair_preco_companhia(d, o["cias"])


def serpapi_buscar(dep, arr, data_iso):
    """Busca os voos e troca o preço pelo que a COMPANHIA cobra (não o menor preço de agências).

    Devolve (lista, info). Só entram na lista voos cujo preço direto na companhia foi encontrado.
    """
    d = _serpapi_get(dict(engine="google_flights", departure_id=",".join(dep), arrival_id=",".join(arr),
                          outbound_date=data_iso, type="2", currency="BRL", hl="pt", gl="br"))
    erro = d.get("error")
    if erro:
        if _sem_resultado(erro):
            return [], {"ocultas": 0}
        raise BuscaErro(_mascarar("SerpApi: " + str(erro)))
    ofertas = [o for o in normalizar_serpapi(d) if o.get("booking_token")]
    candidatos = ofertas[:OPCOES_COMPANHIA]
    if not candidatos:
        return [], {"ocultas": 0}

    def tarefa(o):
        ult = None
        for tentativa in range(2):          # 1 nova tentativa (limite de chamadas simultâneas, falha de rede)
            try:
                return o, _preco_companhia(o, data_iso), None
            except BuscaErro as e:
                ult = e
                time.sleep(1.5)
        return o, None, ult

    with ThreadPoolExecutor(max_workers=5) as ex:
        resultados = list(ex.map(tarefa, candidatos))
    finais, ocultas, ultimo_erro, sem_preco, erros = [], 0, None, [], 0
    for o, pc, err in resultados:
        if err:
            ultimo_erro = err
            erros += 1
            o.pop("booking_token", None)
            sem_preco.append(dict(o, motivo="erro ao conferir"))
            continue
        if not pc:
            ocultas += 1          # só aparece em agências (Decolar, Booking...), não na companhia
            o.pop("booking_token", None)
            sem_preco.append(dict(o, motivo="não vendido direto pela companhia"))
            continue
        o.update(preco=pc["preco"], vendedor=pc["vendedor"], tarifa=pc["tarifa"], bagagem=pc["bagagem"],
                 fonte="companhia")
        o.pop("booking_token", None)
        finais.append(o)
    if not finais and ultimo_erro:
        raise ultimo_erro
    finais.sort(key=lambda o: (o["preco"], o["duracao_min"]))
    return finais, {"ocultas": ocultas, "erros": erros, "sem_preco": sem_preco,
                    "total_google": len(ofertas)}


def gerar_exemplo(dep, arr, data_iso):
    """Dados FICTÍCIOS, só para testar a tela quando não há chave do SerpApi."""
    rnd = random.Random(f"{','.join(dep)}{','.join(arr)}{data_iso}")
    cias = [("LATAM", "LA"), ("GOL", "G3"), ("Azul", "AD")]
    saida = []
    for _ in range(OPCOES_COMPANHIA + 2):
        o, d_ = rnd.choice(dep), rnd.choice(arr)
        cia, sigla = rnd.choice(cias)
        paradas = rnd.choice([0, 0, 1])
        h, m = rnd.choice(range(5, 22)), rnd.choice([0, 10, 25, 40, 55])
        ini = datetime.fromisoformat(data_iso).replace(hour=h, minute=m)
        dur = rnd.randint(60, 150) + paradas * rnd.randint(70, 140)
        fim = ini + timedelta(minutes=dur)
        num = f"{sigla} {rnd.randint(1000, 9999)}"
        google = rnd.randint(260, 1250)
        na_cia = round(google * rnd.choice([1.0, 1.0, 1.15, 1.3, 1.4]))   # companhia costuma ser >= agência
        fmt = "%Y-%m-%d %H:%M"
        saida.append({
            "id": hashlib.sha1(f"{num}{o}{d_}{ini}".encode()).hexdigest()[:12],
            "preco": float(na_cia), "preco_google": float(google),
            "vendedor": cia, "tarifa": rnd.choice(["Econômica", "Light", "Plus"]), "bagagem": "", "fonte": "companhia",
            "cias": [cia],
            "segmentos": [{"cia": cia, "numero": num, "dep_id": o, "dep_nome": o, "dep_hora": ini.strftime(fmt),
                           "arr_id": d_, "arr_nome": d_, "arr_hora": fim.strftime(fmt)}],
            "origem_id": o, "destino_id": d_,
            "partida": ini.strftime(fmt), "chegada": fim.strftime(fmt),
            "duracao_min": dur, "escalas": paradas, "escalas_em": ["CWB"] if paradas else [],
            "exemplo": True,
        })
    ocultas = 2
    saida = sorted(saida, key=lambda o: (o["preco"], o["duracao_min"]))[:max(1, len(saida) - ocultas)]
    return saida, {"ocultas": ocultas}



# --------------------------------------------------------------------------- rotas: público
@bp.get("/")
def index():
    return render_template("cotacao/solicitar.html", ativo="solicitar", hoje=date.today().isoformat())


@bp.get("/api/cidades")
def api_cidades():
    return jsonify(CIDADES)


def _codigos(lista):
    out = []
    for c in lista or []:
        c = str(c).strip().upper()
        if re.fullmatch(r"[A-Z]{3}", c) and c not in out:
            out.append(c)
    return out


@bp.post("/api/buscar")
def api_buscar():
    j = request.get_json(force=True, silent=True) or {}
    origens, destinos = _codigos(j.get("origens")), _codigos(j.get("destinos"))
    origens = [c for c in origens if c not in destinos]   # ex.: saindo de Londrina para São Paulo, não cota GRU->GRU
    if not origens or not destinos:
        return jsonify(erro="Escolha origem e destino diferentes."), 400
    try:
        ida = date.fromisoformat(j.get("data_ida", ""))
        volta = date.fromisoformat(j["data_volta"]) if j.get("data_volta") else None
    except ValueError:
        return jsonify(erro="Datas inválidas."), 400
    if ida < date.today():
        return jsonify(erro="A data de ida não pode ser no passado."), 400
    if volta and volta < ida:
        return jsonify(erro="A volta não pode ser antes da ida."), 400

    modo = modo_busca()
    params = {"origens": sorted(origens), "destinos": sorted(destinos),
              "ida": ida.isoformat(), "volta": volta.isoformat() if volta else None}
    chave = hashlib.sha1((json.dumps(params, sort_keys=True) + modo).encode()).hexdigest()
    limite = (datetime.now() - timedelta(minutes=CACHE_MINUTOS)).isoformat(timespec="seconds")
    c = q_um("SELECT * FROM cotacao_buscas WHERE chave=%s AND criado_em>=%s ORDER BY criado_em DESC LIMIT 1",
             (chave, limite))
    if c:
        return jsonify(busca_id=c["id"], modo=c["modo"], cache=True, criado_em=c["criado_em"],
                       aviso=json.loads(c["params_json"]).get("aviso"),
                       extras=json.loads(c["params_json"]).get("extras", {}),
                       ida=json.loads(c["ida_json"]), volta=json.loads(c["volta_json"]))

    buscador = serpapi_buscar if modo == "serpapi" else gerar_exemplo
    try:
        res_ida, info_ida = buscador(origens, destinos, ida.isoformat())
        res_volta, info_volta = buscador(destinos, origens, volta.isoformat()) if volta else ([], {"ocultas": 0})
    except BuscaErro as e:
        return jsonify(erro=str(e)), 502
    ocultas = info_ida["ocultas"] + info_volta["ocultas"]
    erros = info_ida.get("erros", 0) + info_volta.get("erros", 0)
    partes = []
    if ocultas:
        partes.append(f"{ocultas} opção(ões) não têm preço direto na companhia (só agências) e não podem ser escolhidas.")
    if erros:
        partes.append(f"{erros} opção(ões) não puderam ser conferidas por erro de consulta; busque de novo em instantes.")
    params["aviso"] = " ".join(partes) or None
    params["extras"] = {"ida": info_ida.get("sem_preco", []), "volta": info_volta.get("sem_preco", [])}

    busca_id = secrets.token_hex(8)
    agora = datetime.now().isoformat(timespec="seconds")
    q_exec("INSERT INTO cotacao_buscas (id,chave,criado_em,modo,params_json,ida_json,volta_json) VALUES (%s,%s,%s,%s,%s,%s,%s)",
           (busca_id, chave, agora, modo, json.dumps(params), json.dumps(res_ida), json.dumps(res_volta)))
    return jsonify(busca_id=busca_id, modo=modo, cache=False, criado_em=agora, aviso=params["aviso"], extras=params["extras"],
                   ida=res_ida, volta=res_volta)


def _sim_nao(v):
    return v if v in ("Sim", "Não") else None


@bp.post("/api/solicitar")
def api_solicitar():
    if (request.content_length or 0) > 10 * 1024 * 1024:
        return jsonify(erros=["Arquivo grande demais (máximo 10 MB)."]), 413
    try:
        d = json.loads(request.form.get("dados", "{}"))
    except ValueError:
        return jsonify(erros=["Dados inválidos."]), 400
    erros = []
    v = d.get("viajante") or {}
    for campo, rot in (("nome", "Nome"), ("funcao", "Função"), ("obra", "Obra"), ("cpf", "CPF"), ("nascimento", "Data de nascimento")):
        if not str(v.get(campo, "")).strip():
            erros.append(f"{rot} é obrigatório.")
    if v.get("cpf") and len(re.sub(r"\D", "", v["cpf"])) != 11:
        erros.append("CPF deve ter 11 dígitos.")
    if not d.get("motivo"):
        erros.append("Informe o motivo da viagem.")
    if d.get("trecho") not in ("ida", "ida_volta"):
        erros.append("Informe se a viagem é só ida ou ida e volta.")
    if not d.get("data_ida"):
        erros.append("Informe a data de ida.")
    if d.get("trecho") == "ida_volta" and not d.get("data_volta"):
        erros.append("Informe a data de volta.")
    o, dest = d.get("origem") or {}, d.get("destino") or {}
    if not o.get("cidade") or not dest.get("cidade"):
        erros.append("Informe origem e destino.")
    for campo, rot in (("hospedagem", "Hospedagem"), ("veiculo", "Veículo")):
        d[campo] = _sim_nao(d.get(campo))
        if not d[campo]:
            erros.append(f"Informe se precisa de {rot.lower()}.")

    modal = d.get("modal")
    if modal not in ("aviao", "onibus"):
        erros.append("Escolha ônibus ou avião.")
    melhor_ok = preco_escolhido = preco_melhor = None
    busca_id = escolha_ida = escolha_volta = None
    justificativa = (d.get("justificativa") or "").strip()

    if modal == "aviao":
        d["bagagem"] = _sim_nao(d.get("bagagem"))
        d["inclui_onibus"] = _sim_nao(d.get("inclui_onibus"))
        if not d["bagagem"] or not d["inclui_onibus"]:
            erros.append("Informe bagagem despachada e trajeto de ônibus.")
        busca_id, escolha_ida, escolha_volta = d.get("busca_id"), d.get("escolha_ida"), d.get("escolha_volta")
        b = q_um("SELECT * FROM cotacao_buscas WHERE id=%s", (busca_id or "",))
        if not b:
            erros.append("Faça a busca de opções antes de solicitar.")
        else:
            lista_ida = json.loads(b["ida_json"])
            lista_volta = json.loads(b["volta_json"])
            ofe_ida = next((x for x in lista_ida if x["id"] == escolha_ida), None)
            if not ofe_ida:
                erros.append("Escolha um voo de ida.")
            pares = [(lista_ida, ofe_ida)]
            if d.get("trecho") == "ida_volta":
                ofe_volta = next((x for x in lista_volta if x["id"] == escolha_volta), None)
                if not ofe_volta:
                    erros.append("Escolha um voo de volta.")
                pares.append((lista_volta, ofe_volta))
            if all(of for _, of in pares) and not erros:
                preco_escolhido = sum(of["preco"] for _, of in pares)
                preco_melhor = sum(min(x["preco"] for x in lista) for lista, _ in pares)
                melhor_ok = 1 if all(of["preco"] <= min(x["preco"] for x in lista) + 0.001 for lista, of in pares) else 0
                if not melhor_ok and len(justificativa) < MIN_JUSTIFICATIVA:
                    erros.append(f"Você não escolheu o menor preço. Escreva uma justificativa (mínimo {MIN_JUSTIFICATIVA} caracteres).")
        if melhor_ok == 1:
            justificativa = ""
    else:
        d["acomodacao_onibus"] = d.get("acomodacao_onibus") or ""
        if modal == "onibus" and not d["acomodacao_onibus"]:
            erros.append("Escolha a acomodação no ônibus.")

    documento = None
    arq = request.files.get("documento")
    if arq and arq.filename:
        ext = os.path.splitext(arq.filename)[1].lower()
        if ext not in (".pdf", ".jpg", ".jpeg", ".png"):
            erros.append("O documento deve ser PDF, JPG ou PNG.")
        else:
            documento = secrets.token_hex(8) + ext
    if erros:
        return jsonify(erros=erros), 400
    if documento:
        arq.save(os.path.join(UPLOADS, documento))

    # não guardamos dentro de dados_json o que já tem coluna própria
    for k in ("busca_id", "escolha_ida", "escolha_volta", "justificativa"):
        d.pop(k, None)
    try:
        novo = q_exec(
        "INSERT INTO cotacao_solicitacoes (criado_em,status,dados_json,busca_id,escolha_ida,escolha_volta,melhor_preco_ok,"
        "justificativa,preco_escolhido,preco_melhor,documento) VALUES (%s,'Nova',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (datetime.now().isoformat(timespec="seconds"), json.dumps(d, ensure_ascii=False), busca_id,
         escolha_ida, escolha_volta, melhor_ok, justificativa or None, preco_escolhido, preco_melhor, documento))
    except Exception as exc:  # mostra o motivo real em vez de erro genérico
        return jsonify(erros=[f"Não consegui salvar no banco: {exc}"]), 500
    return jsonify(ok=True, id=novo, melhor_preco=melhor_ok)



# --------------------------------------------------------------------------- admin
def exige_admin(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if ADMIN_PASSWORD:
            auth = request.authorization
            if not auth or not secrets.compare_digest(auth.password or "", ADMIN_PASSWORD):
                return Response("Acesso restrito.", 401, {"WWW-Authenticate": 'Basic realm="Admin"'})
        return f(*a, **kw)
    return wrapper


STATUS = ["Nova", "Em andamento", "Comprada", "Cancelada"]


def _visao(row):
    dados = json.loads(row["dados_json"])
    ida = volta = None
    ofe_ida = ofe_volta = melhor_ida = melhor_volta = None
    modo = None
    if row["busca_id"]:
        b = q_um("SELECT * FROM cotacao_buscas WHERE id=%s", (row["busca_id"],))
        if b:
            modo = b["modo"]
            ida, volta = json.loads(b["ida_json"]), json.loads(b["volta_json"])
            ofe_ida = next((x for x in ida if x["id"] == row["escolha_ida"]), None)
            ofe_volta = next((x for x in volta if x["id"] == row["escolha_volta"]), None)
            melhor_ida = min(ida, key=lambda x: x["preco"]) if ida else None
            melhor_volta = min(volta, key=lambda x: x["preco"]) if volta and dados.get("trecho") == "ida_volta" else None
    return {"r": row, "d": dados, "ida": ida, "volta": volta, "ofe_ida": ofe_ida, "ofe_volta": ofe_volta,
            "melhor_ida": melhor_ida, "melhor_volta": melhor_volta, "modo": modo,
            "dif": (row["preco_escolhido"] - row["preco_melhor"]) if row["preco_escolhido"] is not None else None}


@bp.context_processor
def _ctx():
    try:
        n = list(q_um("SELECT COUNT(*) AS n FROM cotacao_solicitacoes WHERE status='Nova'").values())[0]
    except Exception:
        n = 0
    return {"qtd_novas": n, "modo": modo_busca(), "embed": request.args.get("embed") == "1" or request.form.get("embed") == "1",
            "q": {"embed": 1} if (request.args.get("embed") == "1" or request.form.get("embed") == "1") else {}}


@bp.get("/solicitacoes")
@exige_admin
def solicitacoes():
    rows = q_todos("SELECT * FROM cotacao_solicitacoes ORDER BY id DESC")
    itens = [_visao(r) for r in rows]
    resumo = {
        "total": len(rows),
        "melhor": sum(1 for r in rows if r["melhor_preco_ok"] == 1),
        "justificadas": sum(1 for r in rows if r["melhor_preco_ok"] == 0),
        "novas": sum(1 for r in rows if r["status"] == "Nova"),
    }
    return render_template("cotacao/solicitacoes.html", itens=itens, status_lista=STATUS,
                           resumo=resumo, ativo="solicitacoes")


@bp.get("/admin")
def admin():
    return redirect(url_for("cotacao.solicitacoes", **({"embed": 1} if request.args.get("embed") == "1" else {})))


@bp.post("/solicitacoes/<int:sid>/status")
@exige_admin
def solicitacao_status(sid):
    novo = request.form.get("status")
    if novo in STATUS:
        q_exec("UPDATE cotacao_solicitacoes SET status=%s WHERE id=%s", (novo, sid))
    return redirect(url_for("cotacao.solicitacoes", **({"embed": 1} if request.form.get("embed") == "1" else {})) + f"#s{sid}")


@bp.get("/uploads/<nome>")
@exige_admin
def baixar_doc(nome):
    if not re.fullmatch(r"[0-9a-f]{16}\.(pdf|jpg|jpeg|png)", nome):
        abort(404)
    return send_from_directory(UPLOADS, nome)



# --------------------------------------------------------------------------- filtros de template
@bp.app_template_filter("cot_brl")
def f_brl(v):
    if v is None:
        return "-"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@bp.app_template_filter("cot_dh")
def f_dh(s):
    try:
        return datetime.fromisoformat(s).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return s or "-"


@bp.app_template_filter("cot_data")
def f_data(s):
    try:
        return datetime.fromisoformat(s).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return s or "-"


@bp.app_template_filter("cot_dur")
def f_dur(m):
    m = int(m or 0)
    return f"{m // 60}h{m % 60:02d}"

