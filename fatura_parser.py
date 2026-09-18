"""Le a fatura do cartao corporativo (PDF do Bradesco/Elo, formato "Fatura
Mensal") e separa os lancamentos por pessoa (cada uma tem seu proprio cartao
dentro da fatura da empresa).

Layout da fatura, do jeito que o texto sai do PDF:

  NOME DA PESSOA Cartao 6509 XXXX XXXX 5928
  10/07 LATAM AIR YQHADU SAO PAULO 8.024,92
  11/07 Expedia Sao Paulo 1.436,74
  ...
  Total para NOME DA PESSOA 96.292,21

Cada bloco comeca com a linha "Cartao" e termina na linha "Total para" - a
mesma pessoa pode aparecer em mais de um bloco (cartoes adicionais), nesse
caso os lancamentos e o total sao somados.

Lancamentos de passagem aerea (LATAM AIR / AZUL LINHAS / GOL LINHAS...) tem
o localizador logo depois do nome da companhia - a GOL costuma colar um
sufixo numerico junto (ex.: WSHRPN017), entao sempre usamos os 6 primeiros
caracteres como o localizador de verdade (padrao de 6 caracteres da IATA),
que e o mesmo campo ja usado no resto do sistema pra casar com uma passagem
comprada.
"""

from __future__ import annotations

import re
from typing import Any

import pypdf

_CARTAO_RE = re.compile(
    r"^([A-ZÀ-Ú][A-ZÀ-Ú0-9 .\-]*?)\s+Cart[ãa]o\s+(\d{4}\s+X{4}\s+X{4}\s+\d{4})\s*$"
)
_TOTAL_RE = re.compile(
    r"^Total\s+para\s+(.+?)\s+([\d.,]+)\s*-?\s*$", re.IGNORECASE
)
_DATA_RE = re.compile(r"^(\d{2}/\d{2})\s*(.*)$")
_VALOR_FINAL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*(-)?\s*$")
_COMPANHIA_RE = re.compile(
    r"\b(LATAM\s*AIR|AZUL\s*LINHAS|GOL\s*LINHAS)\w*\s+([A-Z0-9]{6,12})", re.IGNORECASE
)

_COMPANHIA_NOMES = {
    "LATAM": "LATAM",
    "AZUL": "AZUL",
    "GOL": "GOL",
}


def _parse_valor_br(texto: str) -> float:
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _normalizar_nome(nome: str) -> str:
    return re.sub(r"\s+", " ", (nome or "").strip()).upper()


def _identificar_companhia(historico: str) -> tuple[str, str] | None:
    m = _COMPANHIA_RE.search(historico)
    if not m:
        return None
    bruto = m.group(1).upper()
    chave = next((k for k in _COMPANHIA_NOMES if bruto.startswith(k)), bruto.split()[0])
    companhia = _COMPANHIA_NOMES.get(chave, chave)
    localizador = m.group(2).upper()[:6]
    return companhia, localizador


def parse_fatura_pdf(caminho: str) -> dict[str, Any]:
    """Devolve {"pessoas": [{"nome", "cartoes": [...], "total", "quantidade_lancamentos",
    "lancamentos": [...]}]}. "lancamentos" traz TODOS os lancamentos da pessoa (nao so os
    reconhecidos como passagem aerea) - cada item so ganha "companhia"/"localizador" quando
    a gente reconhece o padrao de companhia aerea no historico; os demais aparecem do mesmo
    jeito, sem esses dois campos, pra quem estiver conferindo a fatura ver tudo que e da
    pessoa e decidir o que fazer com o que nao bateu automaticamente."""
    reader = pypdf.PdfReader(caminho)
    texto_completo = "\n".join(page.extract_text() or "" for page in reader.pages)
    linhas = [linha.strip() for linha in texto_completo.splitlines() if linha.strip()]

    pessoas: dict[str, dict[str, Any]] = {}
    ordem: list[str] = []
    pessoa_atual: str | None = None

    for linha in linhas:
        m_cartao = _CARTAO_RE.match(linha)
        if m_cartao:
            nome_exibicao = re.sub(r"\s+", " ", m_cartao.group(1).strip())
            chave = _normalizar_nome(nome_exibicao)
            pessoa_atual = chave
            if chave not in pessoas:
                pessoas[chave] = {
                    "nome": nome_exibicao,
                    "cartoes": [],
                    "total": 0.0,
                    "lancamentos": [],
                }
                ordem.append(chave)
            if m_cartao.group(2) not in pessoas[chave]["cartoes"]:
                pessoas[chave]["cartoes"].append(m_cartao.group(2))
            continue

        m_total = _TOTAL_RE.match(linha)
        if m_total:
            chave = _normalizar_nome(m_total.group(1))
            valor = _parse_valor_br(m_total.group(2))
            if linha.rstrip().endswith("-"):
                valor = -valor
            if chave in pessoas:
                pessoas[chave]["total"] += valor
            pessoa_atual = None
            continue

        if pessoa_atual is None:
            continue

        m_data = _DATA_RE.match(linha)
        if not m_data:
            continue
        resto = m_data.group(2)
        m_valor = _VALOR_FINAL_RE.search(resto)
        if not m_valor:
            continue
        valor = _parse_valor_br(m_valor.group(1))
        if m_valor.group(2) == "-":
            valor = -valor
        historico = resto[: m_valor.start()].strip()
        if not historico:
            continue

        item: dict[str, Any] = {"data": m_data.group(1), "historico": historico, "valor": valor}
        cia = _identificar_companhia(historico)
        if cia:
            item["companhia"], item["localizador"] = cia
        pessoas[pessoa_atual]["lancamentos"].append(item)

    resultado = []
    for chave in ordem:
        p = pessoas[chave]
        resultado.append(
            {
                "nome": p["nome"],
                "cartoes": p["cartoes"],
                "total": round(p["total"], 2),
                "quantidade_lancamentos": len(p["lancamentos"]),
                "lancamentos": p["lancamentos"],
            }
        )
    return {"pessoas": resultado}
