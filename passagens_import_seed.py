import json
import pathlib
import re
import unicodedata

import pdfplumber


PDF_PATH = pathlib.Path(r"C:/Users/notebook/Downloads/INSERIR PORTAL.pdf")
OUTPUT_PATH = pathlib.Path(__file__).with_name("passagens-import-seed.json")


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if "Ã" in text or "�" in text:
        try:
            text = text.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    if "�" in text:
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        if ascii_text:
            text = ascii_text
    return text


def slugify(value):
    base = unicodedata.normalize("NFKD", value or "")
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()
    return base or "registro"


def normalize_date(value):
    text = normalize_text(value)
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not match:
        return ""
    dd, mm, yyyy = match.groups()
    return f"{yyyy}-{mm}-{dd}"


def normalize_money(value):
    text = normalize_text(value)
    if not text or text == "-":
        return ""
    text = text.replace("R$", "").replace(".", "").replace(" ", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return ""
    return f"{number:.2f}"


def map_modalidade(value):
    text = normalize_text(value).upper()
    if "RODO" in text:
        return "Rodoviario"
    if "AER" in text:
        return "Aereo"
    return "Aereo"


def build_seed():
    records = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                headers = [normalize_text(cell).upper() for cell in table[0]]
                if "PASSAGEIRO" not in headers or "OBRA" not in headers:
                    continue
                for row in table[1:]:
                    cells = [normalize_text(cell) for cell in row]
                    if not any(cells):
                        continue
                    item = dict(zip(headers, cells))
                    nome = item.get("PASSAGEIRO", "")
                    if not nome or nome.upper() == "PASSAGEIRO":
                        continue
                    obra = item.get("OBRA", "")
                    data_compra = normalize_date(item.get("DATA DA COMPRA", ""))
                    modalidade = map_modalidade(item.get("MODALIDADE", ""))
                    data_ida = normalize_date(item.get("DATA DE IDA", ""))
                    motivo = normalize_text(item.get("MOTIVO", "")) or "Manual"
                    origem = normalize_text(item.get("ORIGEM", ""))
                    destino = normalize_text(item.get("DESTINO", ""))
                    localizador = normalize_text(item.get("LOCALIZADOR", ""))
                    valor_pago = normalize_money(item.get("VALOR", ""))
                    record_index = len(records) + 1
                    stable_id = f"seed-{data_compra or 'semdata'}-{slugify(nome)}-{slugify(obra)}-{record_index}"
                    records.append(
                        {
                            "row": {
                                "id": stable_id,
                                "tabela": "manual",
                                "tipo": motivo,
                                "nome_colab": nome,
                                "nome_obra": obra,
                                "nome_funcao": "",
                                "data_compra": data_compra,
                                "data_prevista": data_ida,
                                "data_ida": data_ida,
                                "data_ida_volta": "",
                                "valor_aereo": valor_pago if modalidade == "Aereo" else "",
                                "valor_rodoviario": valor_pago if modalidade == "Rodoviario" else "",
                                "valor_pago": valor_pago,
                                "data_chegada": "",
                                "observacao": "Importado do PDF INSERIR PORTAL",
                            },
                            "complement": {
                                "key": f"manual:{stable_id}",
                                "modalidade": modalidade,
                                "dataCompra": data_compra,
                                "origem": origem,
                                "destino": destino,
                                "dataIda": data_ida,
                                "dataVolta": "",
                                "horarioIda": "",
                                "horarioVolta": "",
                                "companhia": "",
                                "localizador": localizador,
                                "numeroPedido": "",
                                "valorAprovado": "",
                                "valorPago": valor_pago,
                                "pagoConfirmado": False,
                                "observacaoInterna": "Carga inicial importada do PDF INSERIR PORTAL",
                            },
                        }
                    )
    payload = {
        "passagensRows": [item["row"] for item in records],
        "passagensComplements": [item["complement"] for item in records],
        "passagensCreditos": [],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = build_seed()
    print(OUTPUT_PATH)
    print(len(payload["passagensRows"]))
