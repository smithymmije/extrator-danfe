from flask import Flask, render_template, request
import os, re, unicodedata
from PyPDF2 import PdfReader

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALVOS = [
    "ACUCAR CRISTAL 5KG PAINEIRAS",
    "CAFE TRAD FORTE ALMOFADA 250GR CAFUSO",
    "FILTRO DE PAPEL N103 30UND BRIGITTA",
]

UNIT_TOKENS = ["UN", "PT", "PC", "FD", "KG", "LT"]
NUM_RE = r"[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}"

def br_to_float(s):
    try:
        return float(s.replace(".", "").replace(",", "."))
    except:
        return None

def fmt_qty(q):
    if q is None:
        return "?"
    try:
        iq = int(q)
        return str(iq) if abs(q - iq) < 1e-6 else str(q)
    except:
        return str(q)

def normalize(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

ALVOS_NORM = [normalize(a) for a in ALVOS]

@app.route("/")
def index():
    return render_template("index.html", resultado="")

@app.route("/processar", methods=["POST"])
def processar():
    if "pdf" not in request.files:
        return "Nenhum arquivo enviado", 400

    pdf_file = request.files["pdf"]
    pdf_path = os.path.join(UPLOAD_FOLDER, pdf_file.filename)
    pdf_file.save(pdf_path)

    # Lê PDF
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [re.sub(r"[ \t]+", " ", ln) for ln in text.splitlines()]
    txt_all = " ".join(lines)

    # NF e Filial
    m_nf = re.search(r"N\.\s*([\d\.]+)\s*SÉRIE", txt_all, re.IGNORECASE)
    nf_num = m_nf.group(1).replace(".", "") if m_nf else "?"
    m_fl = re.search(r"FIL(?:IAL)?\s*(\d{1,3})", txt_all, re.IGNORECASE)
    filial = f"FL{m_fl.group(1)}" if m_fl else "FL?"

    # Extrai item por descrição (alvo)
    def extrair_item_por_descricao(descricao):
        for i, ln in enumerate(lines):
            if descricao in ln:
                pos_desc = ln.find(descricao)
                prefix = ln[:pos_desc]

                unidade = None
                last_unit_match = None
                for ut in UNIT_TOKENS:
                    for m_ut in re.finditer(rf"\b{ut}\b", prefix):
                        last_unit_match = (ut, m_ut)

                vunit = qty = None
                if last_unit_match:
                    unidade, m_unit = last_unit_match
                    win = prefix[max(0, m_unit.start() - 120):m_unit.start()]
                    nums = list(re.finditer(NUM_RE, win))
                    if len(nums) >= 2:
                        vunit = win[nums[-2].start():nums[-2].end()]
                        qty = win[nums[-1].start():nums[-1].end()]
                    elif len(nums) == 1:
                        qty = win[nums[-1].start():nums[-1].end()]

                # fallback linha anterior
                if (vunit is None or qty is None) and i > 0:
                    prev = lines[i - 1]
                    nums2 = list(re.finditer(NUM_RE, prev))
                    if len(nums2) >= 2:
                        vunit = vunit or prev[nums2[-2].start():nums2[-2].end()]
                        qty = qty or prev[nums2[-1].start():nums2[-1].end()]
                    if unidade is None:
                        for ut in UNIT_TOKENS:
                            if re.search(rf"\b{ut}\b", prev):
                                unidade = ut
                                break

                vunit_f = br_to_float(vunit)
                qty_f = br_to_float(qty)

                total = None
                if vunit_f and qty_f:
                    total = round(vunit_f * qty_f, 2)
                else:
                    nums_line = re.findall(NUM_RE, ln)
                    total = br_to_float(nums_line[-1]) if nums_line else None

                return {
                    "descricao": descricao,
                    "descricao_norm": normalize(descricao),
                    "unidade": unidade,
                    "valor_unitario": vunit_f,
                    "quantidade": qty_f,
                    "total": total,
                }
        return None

    # Relatório 1 (alvos)
    alvos_encontrados = []
    for desc in ALVOS:
        it = extrair_item_por_descricao(desc)
        if it and it["quantidade"] is not None:
            alvos_encontrados.append(it)

    partes1 = [f"{fmt_qty(it['quantidade'])} {it['descricao']}" for it in alvos_encontrados]
    relatorio1 = ", ".join(partes1) + f", alocados direto na {filial}, para atender demandas de copa e cozinha, referente a Dezembro/2025 - NF{nf_num} Fornecedor Coletar."
    total_alvos = round(sum((it.get("total") or 0) for it in alvos_encontrados), 2)

    # EXTRAI TODOS OS ITENS
    prod_section_match = re.search(r"DADOS DOS PRODUTOS/SERVIÇOS(.*)ICMS RETIDO", text, re.DOTALL | re.IGNORECASE)
    all_items = []
    if prod_section_match:
        prod_text = prod_section_match.group(1)
        prod_lines = [ln.strip() for ln in prod_text.splitlines() if ln.strip()]

        for ln in prod_lines:
            unidade = None
            unit_pos = None
            for ut in UNIT_TOKENS:
                m_ut = re.search(rf"\b{ut}\b", ln)
                if m_ut:
                    unidade = ut
                    unit_pos = m_ut.start()
            if not unidade:
                continue

            win = ln[max(0, unit_pos - 80):unit_pos]
            nums = list(re.finditer(NUM_RE, win))

            vunit = qty = None
            if len(nums) >= 2:
                vunit = win[nums[-2].start():nums[-2].end()]
                qty = win[nums[-1].start():nums[-1].end()]
            elif len(nums) == 1:
                qty = win[nums[-1].start():nums[-1].end()]

            vunit_f = br_to_float(vunit)
            qty_f = br_to_float(qty)

            nums_line = re.findall(NUM_RE, ln)
            if vunit_f and qty_f:
                total = round(vunit_f * qty_f, 2)
            else:
                total = br_to_float(nums_line[-1]) if nums_line else None

            desc = re.sub(NUM_RE, "", ln)
            desc = re.sub(r"\b\d+\b", "", desc)
            desc = desc.replace(unidade, "").strip()

            all_items.append({
                "descricao": desc,
                "descricao_norm": normalize(desc),
                "unidade": unidade,
                "valor_unitario": vunit_f,
                "quantidade": qty_f,
                "total": total,
            })

    # Remove alvos do conjunto
    alvos_descricoes_exatas = {
    "FILTRO DE PAPEL N103 30UND BRIGITTA",
    "ACUCAR CRISTAL 5KG PAINEIRAS",
    "CAFE TRAD FORTE ALMOFADA 250GR CAFUSO"
    }
    remaining = [it for it in all_items if it["descricao"].strip() not in alvos_descricoes_exatas]




    def unit_price(it):
        if it["valor_unitario"] is not None:
            return it["valor_unitario"]
        if it["total"] and it["quantidade"]:
            return round(it["total"] / it["quantidade"], 2)
        return 0.0

    def total_item(it):
        if it["total"] is not None:
            return it["total"]
        if it["valor_unitario"] and it["quantidade"]:
            return round(it["valor_unitario"] * it["quantidade"], 2)
        return 0.0

    remaining_clean = [it for it in remaining if it["descricao"]]
    total_limpeza = round(sum(total_item(it) for it in remaining_clean), 2)

    # Frete
    m_frete = re.search(r"VALOR DO FRETE\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", text, re.IGNORECASE)
    frete = br_to_float(m_frete.group(1)) if m_frete else 0.0
    total_limpeza_com_frete = round(total_limpeza + frete, 2)

    # Top 2
    top2 = sorted(remaining_clean, key=lambda x: unit_price(x), reverse=True)[:2]
    partes2 = [f"{fmt_qty(it['quantidade'])} {it['descricao']}" for it in top2]
    relatorio2 = ", ".join(partes2) + f", alocados direto na {filial}, para atender demandas de limpeza, referente a Dezembro/2025 - NF{nf_num} Fornecedor Coletar."

    # Monta relatório final (igual ao Colab: dois parágrafos e totais)
    resultado_text = (
        f"{relatorio1}\n\n"
        f"TOTAL ALVOS: R$ {str(total_alvos).replace('.', ',')}\n\n"
        f"{relatorio2}\n\n"
        f"TOTAL LIMPEZA (sem frete): R$ {str(total_limpeza).replace('.', ',')}\n"
        f"FRETE: R$ {str(frete).replace('.', ',')}\n"
        f"TOTAL LIMPEZA + FRETE: R$ {str(total_limpeza_com_frete).replace('.', ',')}"
    )

    # Exibe exatamente como texto (mantendo que o template mostrará dentro de um bloco)
    html = f"<pre style='white-space: pre-wrap;'>{resultado_text}</pre>"
    return render_template("index.html", resultado=html)


if __name__ == "__main__":
    app.run(debug=True)
