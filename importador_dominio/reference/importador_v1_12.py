import re
import sys
import os
import unicodedata
from pathlib import Path
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    # Permite importar parse_pdf em ambientes sem interface gráfica, como
    # execução automatizada da auditoria por gabaritos.
    tk = None
    ttk = filedialog = messagebox = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from openpyxl import Workbook
    from openpyxl.styles import numbers
except ImportError:
    Workbook = None

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageOps
except ImportError:
    pytesseract = None
    Image = None

if pytesseract is not None:
    configured_tesseract = os.environ.get("TESSERACT_CMD")
    default_tesseract = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if configured_tesseract:
        pytesseract.pytesseract.tesseract_cmd = configured_tesseract
    elif os.path.exists(default_tesseract):
        pytesseract.pytesseract.tesseract_cmd = default_tesseract


APP_TITLE = "Importador de Extratos - Domínio v1.12"
DATE_RE = re.compile(r"^\d{2}/\d{2}/(?:\d{2}|\d{4})$")


def brl_to_float(text):
    """Converte texto monetário brasileiro, como 'R$ 1.234,56', em número."""
    cleaned = text.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    return float(cleaned)


def parse_date(text):
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Data inválida: {text}")


def _normalize_bank_text(text):
    """Normaliza acentos, espaços e pontuação para tolerar variações de PDF/OCR."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def _normalize_bank_text(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Z0-9]+", " ", text.upper())
    return " ".join(text.split())


def detect_bank(pdf_text, filename=""):
    """Identifica o emissor por conteúdo e nome do arquivo, sem confundir produtos."""
    upper = _normalize_bank_text(pdf_text)
    fn = _normalize_bank_text(filename)

    # Bloqueios de produto que não deve entrar no fluxo de conta corrente.
    if "SICOOB" in upper and ("EXTRATO DE CARTAO DE CREDITO" in upper or "CONTA CARTAO" in upper):
        return "Sicoob (cartão de crédito - não suportado)"
    if "CAIXA" in upper and ("REM BASICA" in upper or "CRED JUROS" in upper or "FGTS" in upper):
        return "Caixa (produto não confirmado como conta corrente)"

    # Marcadores fortes no nome do arquivo e/ou no cabeçalho.
    if "C6" in fn or "BANCO C6 S A" in upper or "REL DE EXTRATO PERIODICO" in upper:
        return "C6 Bank"
    if "BTG" in fn or ("BTG PACTUAL" in upper and "EXTRATO" in upper):
        return "BTG Pactual"
    if "SICOOB" in fn or ("SISBR" in upper and "EXTRATO" in upper):
        return "Sicoob"
    if "UNICRED" in fn or ("UNICRED" in upper and "EXTRATO" in upper):
        return "Unicred"
    if "BANRISUL" in fn or ("BANRISUL" in upper and ("MOVIMENTOS" in upper or "EXTRATO" in upper)):
        return "Banrisul"
    if "SICREDI" in fn or ("SICREDI" in upper and "EXTRATO" in upper):
        return "Sicredi"
    if "PAGBANK" in fn or "PAGSEGURO" in upper:
        return "PagBank"
    if "BANCO DO BRASIL" in fn or ("EXTRATO DE CONTA CORRENTE" in upper and "BANCO DO BRASIL" in upper):
        return "Banco do Brasil"
    if "CRESOL" in fn or "CRESOL CENTRAL BRASIL" in upper:
        return "Cresol"
    if "VIACREDI" in fn or "VIACREDI" in upper:
        return "Viacredi"
    if "ITAU" in fn or "ITAÚ" in str(filename).upper() or ("EXTRATO CONTA" in upper and "LANÇAMENTOS" in upper):
        return "Itaú"
    if "SAFRA" in fn or "BANCO SAFRA" in upper:
        return "Banco Safra"
    if "SANTANDER" in fn or "SANTANDER" in upper:
        return "Santander"
    if "ORIGINAL" in fn or "BANCO ORIGINAL" in upper:
        return "Banco Original"
    if "BANCO INTER" in fn or "BANCO INTER" in upper:
        return "Banco Inter"
    if "NUBANK" in fn or "NU PAGAMENTOS" in upper or "NUBANK" in upper:
        return "Nubank"
    if "MERCADO PAGO" in fn or "MERCADO PAGO INSTITUICAO" in upper:
        return "Mercado Pago"
    if "ASAAS" in fn or "ASAAS GESTAO FINANCEIRA" in upper:
        return "Asaas"
    if "CORA" in fn or "CORA SOCIEDADE" in upper:
        return "Cora"
    if "STONE" in fn:
        return "Stone (layout identificado)"

    # Stone só pelo conteúdo se a tabela inteira e o período estiverem presentes.
    has_stone_table = all(x in upper for x in ("DATA", "TIPO", "DESCRICAO", "VALOR", "SALDO"))
    if has_stone_table and "PERIODO DE" in upper:
        return "Stone (layout identificado)"
    return "Banco/layout não reconhecido"


def parse_stone_pdf(pdf_path):
    """
    Leitor para o layout Stone testado.
    Extrai apenas DATA, DESCRIÇÃO e VALOR.
    Usa TIPO (Entrada/Saída) somente para determinar o sinal do valor.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF não está instalado. Execute: pip install -r requirements.txt")

    pdf = fitz.open(pdf_path)
    records = []
    issues = []

    for page_number, page in enumerate(pdf, start=1):
        words = page.get_text("words")
        date_anchors = sorted(
            [w for w in words if w[0] < 75 and DATE_RE.match(w[4])],
            key=lambda w: w[1]
        )

        for anchor in date_anchors:
            y = (anchor[1] + anchor[3]) / 2
            type_words = [
                w for w in words
                if 75 <= w[0] < 125
                and abs(((w[1] + w[3]) / 2) - y) < 5
                and w[4].strip().lower() in ("entrada", "saída", "saida")
            ]
            value_words = [
                w for w in words
                if 285 <= w[0] < 355
                and abs(((w[1] + w[3]) / 2) - y) < 5
            ]
            description_words = [
                w for w in words
                if 120 <= w[0] < 285
                and y - 20 <= (w[1] + w[3]) / 2 <= y + 20
            ]

            line_groups = {}
            for word in description_words:
                line_y = round((word[1] + word[3]) / 2, 1)
                line_groups.setdefault(line_y, []).append(word)

            description = " ".join(
                " ".join(w[4] for w in sorted(line, key=lambda item: item[0]))
                for _, line in sorted(line_groups.items())
            ).strip()
            value_text = " ".join(
                w[4] for w in sorted(value_words, key=lambda item: item[0])
            ).strip()
            transaction_type = type_words[0][4].strip().lower() if type_words else ""

            try:
                if not transaction_type:
                    raise ValueError("Tipo Entrada/Saída não identificado")
                if not value_text:
                    raise ValueError("Valor não identificado")
                if not description:
                    raise ValueError("Descrição não identificada")

                value = brl_to_float(value_text)
                value = -abs(value) if transaction_type in ("saída", "saida") else abs(value)

                records.append({
                    "date": parse_date(anchor[4]),
                    "value": value,
                    "description": description,
                    "source": Path(pdf_path).name,
                    "page": page_number,
                    "review": False,
                    "note": ""
                })
            except Exception as exc:
                issues.append({
                    "source": Path(pdf_path).name,
                    "page": page_number,
                    "date_text": anchor[4],
                    "reason": str(exc),
                    "description": description,
                    "value_text": value_text
                })

    pdf.close()
    return records, issues


def parse_sicredi_pdf(pdf_path):
    """
    Leitor do layout Sicredi testado no extrato enviado.
    Exporta DATA, DESCRIÇÃO e VALOR.
    Usa o saldo do extrato apenas para validar a sequência dos lançamentos.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF não está instalado. Execute: pip install -r requirements.txt")

    pdf = fitz.open(pdf_path)
    records = []
    issues = []
    opening_balance = None
    balance_rows = []

    for page_number, page in enumerate(pdf, start=1):
        words = page.get_text("words")

        # Captura o saldo anterior para conferir a sequência desde o início.
        if page_number == 1:
            saldo_words = [w for w in words if w[4].upper() == "SALDO"]
            anterior_words = [w for w in words if w[4].upper() == "ANTERIOR"]
            if saldo_words and anterior_words:
                target_y = (saldo_words[0][1] + saldo_words[0][3]) / 2
                candidates = [
                    w for w in words
                    if w[0] >= 520 and abs(((w[1] + w[3]) / 2) - target_y) < 5
                ]
                if candidates:
                    try:
                        opening_balance = brl_to_float(
                            " ".join(w[4] for w in sorted(candidates, key=lambda item: item[0]))
                        )
                    except Exception:
                        opening_balance = None

        date_anchors = sorted(
            [w for w in words if w[0] < 95 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", w[4])],
            key=lambda w: w[1]
        )

        for anchor in date_anchors:
            y = (anchor[1] + anchor[3]) / 2

            # Coluna Descrição: começa aproximadamente em x=99 e termina antes de Documento.
            description_words = [
                w for w in words
                if 95 <= w[0] < 375
                and abs(((w[1] + w[3]) / 2) - y) < 4
            ]
            # Coluna Valor (R$), sem capturar o saldo que fica mais à direita.
            value_words = [
                w for w in words
                if 450 <= w[0] < 515
                and abs(((w[1] + w[3]) / 2) - y) < 4
            ]
            # Saldo é lido apenas para validação, nunca exportado.
            balance_words = [
                w for w in words
                if 520 <= w[0] < 580
                and abs(((w[1] + w[3]) / 2) - y) < 4
            ]

            description = " ".join(
                w[4] for w in sorted(description_words, key=lambda item: item[0])
            ).strip()
            value_text = " ".join(
                w[4] for w in sorted(value_words, key=lambda item: item[0])
            ).strip()
            # PDFs com marca d'água podem inserir palavras na mesma região do saldo.
            # Mantemos somente tokens com formato monetário brasileiro.
            money_tokens = [
                w[4] for w in sorted(balance_words, key=lambda item: item[0])
                if re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}", w[4])
            ]
            balance_text = money_tokens[0] if len(money_tokens) == 1 else ""

            try:
                if not description:
                    raise ValueError("Descrição não identificada")
                if not value_text:
                    raise ValueError("Valor não identificado")

                value = brl_to_float(value_text)
                date_value = parse_date(anchor[4])

                records.append({
                    "date": date_value,
                    "value": value,
                    "description": description,
                    "source": Path(pdf_path).name,
                    "page": page_number,
                    "review": False,
                    "note": ""
                })

                if balance_text:
                    balance_rows.append({
                        "date": date_value,
                        "value": value,
                        "balance": brl_to_float(balance_text),
                        "page": page_number,
                        "date_text": anchor[4]
                    })
                else:
                    issues.append({
                        "source": Path(pdf_path).name,
                        "page": page_number,
                        "date_text": anchor[4],
                        "reason": "Saldo da linha não localizado para conferência.",
                        "description": description,
                        "value_text": value_text
                    })

            except Exception as exc:
                issues.append({
                    "source": Path(pdf_path).name,
                    "page": page_number,
                    "date_text": anchor[4],
                    "reason": str(exc),
                    "description": description,
                    "value_text": value_text
                })

    pdf.close()

    # Validação aritmética do saldo: saldo anterior + movimento = novo saldo.
    # O saldo não é exportado; serve somente como controle de integridade.
    if opening_balance is not None:
        expected_balance = opening_balance
        for item in balance_rows:
            expected_balance = round(expected_balance + item["value"], 2)
            if abs(expected_balance - item["balance"]) > 0.01:
                issues.append({
                    "source": Path(pdf_path).name,
                    "page": item["page"],
                    "date_text": item["date_text"],
                    "reason": (
                        "Divergência na conferência do saldo: "
                        f"esperado R$ {expected_balance:,.2f}, "
                        f"PDF informa R$ {item['balance']:,.2f}."
                    ),
                    "description": "",
                    "value_text": ""
                })
            expected_balance = item["balance"]

    return records, issues



# ---------------------------------------------------------------------------
# Leitores adicionais: C6, BTG Pactual, Sicoob, Unicred e Banrisul.
# Caixa fica intencionalmente fora: o PDF recebido apresenta REM BASICA e
# CRED JUROS, características de poupança, e não confirma conta corrente.
# ---------------------------------------------------------------------------

MONEY_RE = re.compile(r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")


def _money_token_to_float(token):
    token = str(token).replace("R$", "").replace(" ", "").replace("\u00a0", "")
    token = token.replace("−", "-")
    return brl_to_float(token)


def _new_record(date_text, value, description, pdf_path, page_number):
    return {
        "date": parse_date(date_text),
        "value": round(float(value), 2),
        "description": " ".join(str(description).split()).strip(),
        "source": Path(pdf_path).name,
        "page": page_number,
        "review": False,
        "note": ""
    }


def _issue(pdf_path, page_number, date_text, reason, description="", value_text=""):
    return {
        "source": Path(pdf_path).name,
        "page": page_number,
        "date_text": date_text,
        "reason": reason,
        "description": description,
        "value_text": value_text
    }


def _ocr_page(page, scale=3):
    if pytesseract is None or Image is None:
        raise RuntimeError(
            "Este PDF exige OCR. Instale Pillow e pytesseract e também o Tesseract OCR "
            "para Windows (com idioma português) conforme o README."
        )
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    data = pytesseract.image_to_data(
        image, lang="por", config="--psm 6", output_type=pytesseract.Output.DICT
    )
    words = []
    for i, raw in enumerate(data["text"]):
        text = str(raw).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = 0
        if conf < 15:
            continue
        x, y = int(data["left"][i]), int(data["top"][i])
        w, h = int(data["width"][i]), int(data["height"][i])
        words.append({"x": x, "y": y, "w": w, "h": h, "text": text, "cy": y + h / 2})
    return words


def _ocr_page_with_psm(page, scale=3, psm=11, enhance=False):
    """OCR alternativo com coordenadas em pixels da imagem renderizada."""
    if pytesseract is None or Image is None:
        raise RuntimeError("Tesseract OCR/Pillow não disponível.")
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if enhance:
        image = ImageOps.grayscale(image)
        image = ImageEnhance.Contrast(image).enhance(2.0)
    data = pytesseract.image_to_data(
        image, lang="por", config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )
    words = []
    for i, raw in enumerate(data.get("text", [])):
        token = str(raw).strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = 0
        if conf < 15:
            continue
        x, y = int(data["left"][i]), int(data["top"][i])
        w, h = int(data["width"][i]), int(data["height"][i])
        words.append({"x": x, "y": y, "w": w, "h": h, "text": token, "cy": y + h / 2})
    return words


def _words_text(words):
    return " ".join(w["text"] for w in sorted(words, key=lambda z: (z["y"], z["x"])))


def parse_c6_pdf(pdf_path):
    """C6: usa as colunas DATA, DESCRIÇÃO, VALOR e D/C do extrato periódico."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    date_re = re.compile(r"\d{2}/\d{2}/\d{4}")
    for page_number, page in enumerate(pdf, 1):
        words = page.get_text("words")
        anchors = sorted(
            [w for w in words if w[0] < 80 and date_re.fullmatch(w[4])],
            key=lambda w: w[1]
        )
        for idx, anchor in enumerate(anchors):
            y = (anchor[1] + anchor[3]) / 2
            desc_words = [w for w in words if 80 <= w[0] < 455 and abs(((w[1]+w[3])/2)-y) <= 3.5]
            description = " ".join(w[4] for w in sorted(desc_words, key=lambda z: z[0])).strip()
            if not description or description.upper().startswith("SALDO"):
                continue
            row_values = [w for w in words if 565 <= w[0] < 615 and abs(((w[1]+w[3])/2)-y) <= 4]
            dc_words = [w for w in words if 610 <= w[0] < 645 and abs(((w[1]+w[3])/2)-y) <= 5 and w[4].upper() in ("D", "C")]
            value_tokens = [w[4] for w in sorted(row_values, key=lambda z:z[0]) if MONEY_RE.fullmatch(w[4])]
            try:
                if len(value_tokens) != 1 or len(dc_words) != 1:
                    raise ValueError("Valor ou indicador D/C não identificado de forma única")
                value = _money_token_to_float(value_tokens[0])
                if dc_words[0][4].upper() == "D":
                    value = -abs(value)
                else:
                    value = abs(value)
                records.append(_new_record(anchor[4], value, description, pdf_path, page_number))
            except Exception as exc:
                issues.append(_issue(pdf_path, page_number, anchor[4], str(exc), description, " ".join(value_tokens)))
    pdf.close()
    return records, issues



def parse_c6_ocr_pdf(pdf_path):
    """C6: OCR do extrato cuja camada de texto do PDF vem codificada incorretamente."""
    if pytesseract is None or Image is None:
        raise RuntimeError("O extrato C6 exige OCR. Instale pytesseract, Pillow e Tesseract OCR com idioma português.")

    pdf = fitz.open(pdf_path)
    records, issues = [], []
    date_line = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$")
    # Alguns PDFs C6 antigos perdem a vírgula decimal no OCR (ex.: 5,97 vira 597).
    # Como o extrato sempre imprime centavos, aceitamos o token inteiro e recolocamos
    # a vírgula antes dos dois últimos dígitos. O registro continua marcado para revisão.
    trailing_amount = re.compile(
        r"(?P<amount>(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}|\d{1,8})"
        r"(?:\s*(?P<dc>[A-Z€]{1,2}))?\s*$"
    )

    try:
        for page_number, page in enumerate(pdf, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # PSM 4 preserva melhor as linhas da tabela deste modelo de extrato.
            page_text = pytesseract.image_to_string(image, lang="por", config="--psm 4")

            for raw_line in page_text.splitlines():
                line = " ".join(raw_line.split())
                match = date_line.match(line)
                if not match:
                    continue

                date_text, body = match.groups()
                upper_body = body.upper()

                # Saldos inicial/final/disponível não são movimentações.
                if "SALDO" in upper_body:
                    continue

                amount_match = trailing_amount.search(body)
                if not amount_match:
                    issues.append(_issue(
                        pdf_path, page_number, date_text,
                        "OCR encontrou uma linha com data, mas não conseguiu ler o valor monetário com segurança.",
                        body, ""
                    ))
                    continue

                amount_text = amount_match.group("amount")
                if "," not in amount_text:
                    # A vírgula foi omitida pelo OCR; os dois últimos algarismos são centavos.
                    digits = re.sub(r"\D", "", amount_text)
                    if len(digits) < 3:
                        issues.append(_issue(
                            pdf_path, page_number, date_text,
                            "Valor OCR incompleto: não foi possível recuperar os centavos com segurança.",
                            body, amount_text
                        ))
                        continue
                    amount_text = digits[:-2] + "," + digits[-2:]
                dc_raw = (amount_match.group("dc") or "").upper()
                dc = "D" if "D" in dc_raw else ("C" if any(ch in dc_raw for ch in "C€OQ") else "")
                description = body[:amount_match.start()].strip()
                description = re.sub(r"\b\d{8,}\b", "", description)
                description = " ".join(description.split()).strip(" -|")

                if not description:
                    issues.append(_issue(pdf_path, page_number, date_text,
                                          "Histórico não identificado pelo OCR.", "", amount_text))
                    continue

                # O OCR frequentemente confunde C com €, O ou outros caracteres.
                # A direção é definida pelo texto da movimentação quando inequívoco.
                desc_upper = _normalize_bank_text(description)
                if any(k in desc_upper for k in (
                    "PIX RECEBIDO", "RECEBIMENTO", "CREDITO", "TED RECEBIDA", "DOC RECEBIDO"
                )):
                    value = abs(_money_token_to_float(amount_text))
                elif any(k in desc_upper for k in (
                    "TRANSF ENVIADA", "DEBITO", "SAQUE", "PAGAMENTO", "COMPRA", "RECARGA"
                )):
                    value = -abs(_money_token_to_float(amount_text))
                elif dc == "D":
                    value = -abs(_money_token_to_float(amount_text))
                elif dc == "C":
                    value = abs(_money_token_to_float(amount_text))
                else:
                    issues.append(_issue(
                        pdf_path, page_number, date_text,
                        "Não foi possível determinar com segurança se o lançamento é crédito ou débito.",
                        description, amount_text
                    ))
                    continue

                rec = _new_record(date_text, value, description, pdf_path, page_number)
                rec["review"] = True
                rec["note"] = "Extraído por OCR; conferir histórico, valor e sinal com o PDF original."
                records.append(rec)
    finally:
        pdf.close()

    return records, issues

def parse_btg_pdf(pdf_path):
    """BTG: extrai a coluna Descrição e respeita o sinal explícito do valor."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    date_re = re.compile(r"\d{2}/\d{2}/\d{4}")
    for page_number, page in enumerate(pdf, 1):
        words = page.get_text("words")
        anchors = sorted([w for w in words if w[0] < 100 and date_re.fullmatch(w[4])], key=lambda w:w[1])
        for anchor in anchors:
            y = (anchor[1] + anchor[3]) / 2
            desc_words = [w for w in words if 370 <= w[0] < 640 and abs(((w[1]+w[3])/2)-y) <= 4]
            description = " ".join(w[4] for w in sorted(desc_words, key=lambda z:z[0])).strip()
            if "SALDO DIARIO" in description.upper() or "SALDO DIÁRIO" in description.upper():
                continue
            value_words = [w for w in words if w[0] >= 640 and abs(((w[1]+w[3])/2)-y) <= 4]
            amount_tokens = [w[4] for w in value_words if re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", w[4])]
            negative = any(w[4].startswith("-") for w in value_words)
            try:
                if len(amount_tokens) != 1:
                    raise ValueError("Valor da movimentação não identificado de forma única")
                if not description:
                    raise ValueError("Descrição não identificada")
                value = _money_token_to_float(amount_tokens[0])
                value = -abs(value) if negative else abs(value)
                records.append(_new_record(anchor[4], value, description, pdf_path, page_number))
            except Exception as exc:
                issues.append(_issue(pdf_path, page_number, anchor[4], str(exc), description, " ".join(amount_tokens)))
    pdf.close()
    return records, issues


def _period_month_year(text):
    m = re.search(r"PER[IÍ]ODO\s*:?\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text, re.I)
    if m:
        return int(m.group(2)), int(m.group(3))
    return None, None


def parse_sicoob_pdf(pdf_path):
    """Sicoob SISBR: datas dd/mm sem ano, valor com D/C e histórico multilinha."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    first_text = "\n".join(p.get_text() for p in pdf)
    month, year = _period_month_year(first_text)
    if not month or not year:
        pdf.close()
        return [], [_issue(pdf_path, "-", "", "Período do extrato não identificado para completar o ano das datas.")]

    for page_number, page in enumerate(pdf, 1):
        words = page.get_text("words")
        anchors = []
        # O campo DATA vem em tokens separados e nem todos compartilham a mesma linha-base.
        day_tokens = [w for w in words if 135 <= w[0] < 155 and 215 < w[1] < 930 and re.fullmatch(r"\d{1,2}/?", w[4])]
        month_tokens = [w for w in words if 155 <= w[0] < 180 and 215 < w[1] < 930 and re.fullmatch(r"\d{1,2}", w[4])]
        for dw in day_tokens:
            candidates = [mw for mw in month_tokens if abs(((mw[1]+mw[3])/2)-((dw[1]+dw[3])/2)) <= 3]
            if not candidates:
                continue
            mw = min(candidates, key=lambda z: abs(((z[1]+z[3])/2)-((dw[1]+dw[3])/2)))
            day = int(dw[4].replace("/", "")); mon = int(mw[4])
            if mon == month and 1 <= day <= 31:
                cy = (((dw[1]+dw[3])/2)+((mw[1]+mw[3])/2))/2
                anchors.append((cy, f"{day:02d}/{mon:02d}/{year}"))
        anchors.sort()
        for i, (y, date_text) in enumerate(anchors):
            next_y = anchors[i+1][0] if i+1 < len(anchors) else 940
            row_words = [w for w in words if 185 <= w[0] < 550 and y-5 <= (w[1]+w[3])/2 < next_y-3]
            lines = {}
            for w in row_words:
                ly = round((w[1]+w[3])/2 / 3) * 3
                lines.setdefault(ly, []).append(w)
            desc_parts = []
            for ly, line in sorted(lines.items()):
                line_text = " ".join(w[4] for w in sorted(line,key=lambda z:z[0])).strip()
                up = line_text.upper()
                if not line_text or any(k in up for k in ("SALDO", "CODIGO", "CÓDIGO", "DOC.:", "RESUMO", "LIMITE CONTA", "DISPONÍVEL")):
                    continue
                if re.fullmatch(r"[0-9.\-/]+", line_text):
                    continue
                desc_parts.append(line_text)
            description = " ".join(desc_parts).strip()
            # Valor aparece ligeiramente acima ou abaixo da linha da data; saldo fica em linhas próprias.
            amount_words = [w for w in words if w[0] >= 550 and abs((w[1]+w[3])/2-y) <= 12 and re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}[DC]?", w[4])]
            try:
                if not description or "SALDO" in description.upper():
                    continue
                if len(amount_words) != 1:
                    raise ValueError("Valor da movimentação não identificado de forma única")
                token = amount_words[0][4]
                suffix = token[-1] if token[-1:] in ("D", "C") else ""
                numeric = token[:-1] if suffix else token
                # Em Sicoob, D/C é exibido ao lado/abaixo do valor.
                dc_words = [w for w in words if w[0] >= 595 and abs((w[1]+w[3])/2-y) <= 18 and w[4].upper() in ("D", "C")]
                if suffix:
                    direction = suffix
                elif dc_words:
                    direction = min(dc_words, key=lambda z: abs((z[1]+z[3])/2-y))[4].upper()
                else:
                    raise ValueError("Indicador D/C não identificado")
                value = _money_token_to_float(numeric)
                value = -abs(value) if direction == "D" else abs(value)
                records.append(_new_record(date_text, value, description, pdf_path, page_number))
            except Exception as exc:
                issues.append(_issue(pdf_path, page_number, date_text, str(exc), description, " ".join(w[4] for w in amount_words)))
    pdf.close()
    return records, issues


def parse_unicred_pdf(pdf_path):
    """Unicred: OCR das colunas Débito/Crédito, pois o PDF usa fonte sem mapeamento Unicode."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    try:
        for page_number, page in enumerate(pdf, 1):
            words = _ocr_page(page, scale=3)
            anchors = sorted([w for w in words if w["x"] < 300 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", w["text"])], key=lambda w:w["y"])
            for i, anchor in enumerate(anchors):
                y = anchor["cy"]
                next_y = anchors[i+1]["y"] if i+1 < len(anchors) else 1700
                desc_words = [w for w in words if 250 <= w["x"] < 1400 and anchor["y"]-5 <= w["cy"] < next_y-4]
                desc_parts=[]
                for w in sorted(desc_words,key=lambda z:(z["y"],z["x"])):
                    t=w["text"].strip()
                    if re.fullmatch(r"[0-9.\-/]+",t) or t.upper() in ("D","C","CC") or t in ("(",")","(0)","|","(0)"):
                        continue
                    if t.upper() in ("DOC", "DOC.", "CODIGO", "CÓDIGO"):
                        continue
                    desc_parts.append(t)
                description=" ".join(desc_parts).strip()
                if "SALDO ANTERIOR" in description.upper() or "SALDO DO DIA" in description.upper():
                    continue
                debits=[w for w in words if 1400 <= w["x"] < 1690 and abs(w["cy"]-y)<=22 and re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w["text"])]
                credits=[w for w in words if 1690 <= w["x"] < 1970 and abs(w["cy"]-y)<=22 and re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w["text"])]
                try:
                    if not description:
                        raise ValueError("Histórico não identificado")
                    if len(debits)+len(credits) != 1:
                        raise ValueError("Valor não identificado de forma única nas colunas Débito/Crédito")
                    if debits:
                        value=-abs(_money_token_to_float(debits[0]["text"]))
                    else:
                        value=abs(_money_token_to_float(credits[0]["text"]))
                    rec = _new_record(anchor["text"],value,description,pdf_path,page_number)
                    rec["review"] = True  # OCR pode confundir caracteres de históricos; exige conferência visual.
                    rec["note"] = "Extraído por OCR; conferir com o PDF original."
                    records.append(rec)
                except Exception as exc:
                    issues.append(_issue(pdf_path,page_number,anchor["text"],str(exc),description," ".join(w["text"] for w in debits+credits)))
    finally:
        pdf.close()
    return records, issues


def parse_banrisul_pdf(pdf_path):
    """Banrisul: OCR do extrato mensal; débito é indicado por hífen após o valor."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    month_map = {"JAN":1,"FEV":2,"MAR":3,"ABR":4,"MAI":5,"JUN":6,"JUL":7,"AGO":8,"SET":9,"OUT":10,"NOV":11,"DEZ":12}
    month = year = current_day = None
    started = False
    opening_balance = None
    previous_balance = None
    pending_day_total = 0.0
    money_end = re.compile(r"(?P<amount>(?:\d{1,3}(?:\.\d{3})+|\d+),\s?\d{2})\s*(?P<minus>-)?\s*$")
    try:
        for page_number, page in enumerate(pdf, 1):
            # A última página deste arquivo é um recibo avulso, não o extrato.
            page_words = _ocr_page(page, scale=3)
            page_text = " ".join(w["text"] for w in page_words)
            if "RECIBO" in page_text.upper() and "PAGAMENTO" in page_text.upper():
                continue
            # Linhas OCR ordenadas verticalmente para preservar agrupamento de movimentações.
            lines=[]
            # Agrupa por proximidade vertical para não separar o valor da descrição
            # quando o OCR posiciona dois tokens vizinhos em linhas-base ligeiramente diferentes.
            for w in sorted(page_words, key=lambda z:z["cy"]):
                if not lines or abs(w["cy"] - sum(z["cy"] for z in lines[-1]) / len(lines[-1])) > 5:
                    lines.append([w])
                else:
                    lines[-1].append(w)
            for line_words in lines:
                line=" ".join(w["text"] for w in sorted(line_words,key=lambda z:z["x"]))
                up=line.upper()
                mm=re.search(r"MOVIMENTOS\s+([A-Z]{3})\s*/\s*(20\d{2})",up)
                if mm:
                    month=month_map.get(mm.group(1)); year=int(mm.group(2)); started=True
                    continue
                if "DIA HISTORICO DOCUMENTO VALOR" in up:
                    started=True
                    continue
                if not started:
                    continue
                if "SALDO ANT EM" in up:
                    opening_match = money_end.search(line)
                    if opening_match:
                        opening_balance = _money_token_to_float(opening_match.group("amount").replace(" ", ""))
                        if opening_match.group("minus"):
                            opening_balance = -abs(opening_balance)
                        previous_balance = opening_balance
                    continue
                if "SALDO NA DATA" in up:
                    balance_match = money_end.search(line)
                    if balance_match and previous_balance is not None:
                        closing = _money_token_to_float(balance_match.group("amount").replace(" ", ""))
                        if balance_match.group("minus"):
                            closing = -abs(closing)
                        expected = round(previous_balance + pending_day_total, 2)
                        if abs(expected - closing) > 0.02:
                            issues.append(_issue(
                                pdf_path, page_number,
                                f"{(current_day or 1):02d}/{(month or 1):02d}/{(year or 2000)}",
                                f"Conferência do saldo diário divergiu: esperado R$ {expected:.2f}, PDF informa R$ {closing:.2f}.",
                                "SALDO NA DATA", balance_match.group("amount")
                            ))
                        previous_balance = closing
                        pending_day_total = 0.0
                    continue
                # Captura o dia quando a linha inicia um novo grupo; linhas seguintes herdam o dia.
                day_match=re.match(r"^\s*(\d{1,2})\s+(.+)$",line)
                body=line.strip()
                if day_match and int(day_match.group(1)) <= 31:
                    current_day=int(day_match.group(1)); body=day_match.group(2).strip()
                if not current_day or not month or not year:
                    continue
                if not body or "SALDO" in body.upper():
                    continue
                m=money_end.search(body)
                if not m:
                    continue
                amount_text=m.group("amount").replace(" ","")
                negative=bool(m.group("minus"))
                desc_and_doc=body[:m.start()].strip()
                # Remove o número do documento final, preservando o histórico.
                desc_and_doc=re.sub(r"\s+\d{3,}\s*$", "", desc_and_doc).strip()
                if not desc_and_doc or desc_and_doc.upper().startswith(("SALDO", "LIMITE", "TAXA", "CET")):
                    continue
                try:
                    date_text=f"{current_day:02d}/{month:02d}/{year}"
                    value=_money_token_to_float(amount_text)
                    value=-abs(value) if negative else abs(value)
                    rec = _new_record(date_text,value,desc_and_doc,pdf_path,page_number)
                    rec["review"] = True  # OCR pode confundir sinais ou caracteres; exige conferência visual.
                    rec["note"] = "Extraído por OCR; conferir com o PDF original."
                    records.append(rec)
                    pending_day_total = round(pending_day_total + value, 2)
                except Exception as exc:
                    issues.append(_issue(pdf_path,page_number,f"{current_day:02d}/{month:02d}/{year}",str(exc),desc_and_doc,amount_text))
    finally:
        pdf.close()
    return records, issues



# ---------------------------------------------------------------------------
# Leitores adicionais v1.4 - implementados a partir dos PDFs originais enviados.
# ---------------------------------------------------------------------------

def _page_words_by_y(page, y, tolerance=3.5):
    return [w for w in page.get_text("words") if abs(((w[1] + w[3]) / 2) - y) <= tolerance]


def parse_cresol_pdf(pdf_path):
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    for pn,page in enumerate(pdf,1):
        words=page.get_text("words")
        anchors=sorted([w for w in words if w[0] < 135 and re.fullmatch(r"\d{2}/\d{2}/\d{4}",w[4])],key=lambda w:w[1])
        for a in anchors:
            y=(a[1]+a[3])/2
            row=_page_words_by_y(page,y,4.2)
            desc=" ".join(w[4] for w in sorted([w for w in row if 140 <= w[0] < 640],key=lambda w:w[0])).strip()
            if "GCC.1.80.7" in desc or "PAGINA" in desc.upper():
                continue
            amount=[w for w in row if 640 <= w[0] < 682 and re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w[4])]
            dc=[w[4].upper() for w in row if 681 <= w[0] < 700 and w[4].upper() in ("D","C")]
            if "SALDO ANTERIOR" in desc.upper() or not desc:
                continue
            try:
                desc_norm = _normalize_bank_text(desc)
                amount_text = None
                if len(amount) == 1:
                    amount_text = amount[0][4]
                elif len(amount) == 0 and "DEBITO AUTOMATICO" in desc_norm:
                    # Neste layout específico, as duas parcelas aparecem com o valor
                    # no final da descrição e sem a coluna D/C posicionada na linha.
                    m_amount = re.search(r"((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})\s*$", desc)
                    if m_amount:
                        amount_text = m_amount.group(1)
                        desc = desc[:m_amount.start()].strip()
                if not amount_text:
                    raise ValueError("Valor não identificado de forma única")
                if len(dc) == 1:
                    is_debit = dc[0] == "D"
                elif "DEBITO AUTOMATICO" in desc_norm:
                    is_debit = True
                elif "CREDITO" in desc_norm:
                    is_debit = False
                else:
                    raise ValueError("Indicador D/C ausente e descrição não determina a natureza do lançamento")
                val = _money_token_to_float(amount_text)
                val = -abs(val) if is_debit else abs(val)
                records.append(_new_record(a[4],val,desc,pdf_path,pn))
            except Exception as e: issues.append(_issue(pdf_path,pn,a[4],str(e),desc," ".join(w[4] for w in amount)))
    pdf.close(); return records,issues


def parse_viacredi_pdf(pdf_path):
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    for pn,page in enumerate(pdf,1):
        words=page.get_text("words")
        anchors=sorted([w for w in words if w[0] < 90 and re.fullmatch(r"\d{2}/\d{2}/\d{4}",w[4])],key=lambda w:w[1])
        for a in anchors:
            y=(a[1]+a[3])/2; row=_page_words_by_y(page,y,4.0)
            desc=" ".join(w[4] for w in sorted([w for w in row if 90 <= w[0] < 365],key=lambda w:w[0])).strip()
            deb=[w for w in row if 565 <= w[0] < 650 and re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w[4])]
            cred=[w for w in row if 460 <= w[0] < 550 and re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w[4])]
            if "SALDO ANTERIOR" in desc.upper() or not desc: continue
            try:
                if len(deb)+len(cred)!=1: raise ValueError("Valor não identificado de forma única na coluna Débito/Crédito")
                val=_money_token_to_float((deb or cred)[0][4])
                records.append(_new_record(a[4],val,desc,pdf_path,pn))
            except Exception as e: issues.append(_issue(pdf_path,pn,a[4],str(e),desc," ".join(w[4] for w in deb+cred)))
    pdf.close(); return records,issues


def parse_itau_pdf(pdf_path):
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    for pn,page in enumerate(pdf,1):
        words=page.get_text("words")
        anchors=sorted([w for w in words if w[0] < 115 and re.fullmatch(r"\d{2}/\d{2}/\d{4}",w[4])],key=lambda w:w[1])
        for a in anchors:
            y=(a[1]+a[3])/2; row=_page_words_by_y(page,y,4.5)
            desc=" ".join(w[4] for w in sorted([w for w in row if 115 <= w[0] < 510],key=lambda w:w[0])).strip()
            vals=[w for w in row if 510 <= w[0] < 630 and re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}",w[4])]
            if "SALDO DO DIA" in desc.upper() or not desc: continue
            try:
                if len(vals)!=1: raise ValueError("Valor não identificado de forma única na coluna Valor")
                records.append(_new_record(a[4],_money_token_to_float(vals[0][4]),desc,pdf_path,pn))
            except Exception as e: issues.append(_issue(pdf_path,pn,a[4],str(e),desc," ".join(w[4] for w in vals)))
    pdf.close(); return records,issues


def parse_bb_pdf(pdf_path):
    """Banco do Brasil: texto nativo, sinal separado ou anexado ao valor."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    money_re=re.compile(r"((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})(?:\s*(\(\+\)|\(-\)))?")
    for pn,page in enumerate(pdf,1):
        words=page.get_text("words")
        anchors=sorted([w for w in words if w[0] < 100 and re.fullmatch(r"\d{2}/\d{2}/\d{4}",w[4])],key=lambda w:w[1])
        for ix,a in enumerate(anchors):
            y0=(a[1]+a[3])/2
            y1=(anchors[ix+1][1]+anchors[ix+1][3])/2 if ix+1<len(anchors) else page.rect.height
            block=[w for w in words if y0-2 <= (w[1]+w[3])/2 < y1-2]
            desc=" ".join(w[4] for w in sorted([w for w in block if 100 <= w[0] < 630],key=lambda w:(round(w[1],1),w[0]))).strip()
            compact=re.sub(r"\s+", "", desc.upper())
            if "SALDOANTERIOR" in compact or "ALDO" in compact or re.search(r"S\s*A\s*L\s*D\s*O",desc.upper()) or "SALDODODIA" in compact or not desc:
                continue
            raw_tokens=[w for w in block if w[0]>=630]
            candidates=[]
            for w in raw_tokens:
                m=money_re.fullmatch(w[4])
                if m:
                    candidates.append((m.group(1),m.group(2),w[4]))
            # Em alguns PDFs o sinal fica em uma palavra ao lado do valor.
            signs=[w[4] for w in raw_tokens if w[4] in ("(+)","(-)")]
            try:
                if len(candidates)!=1:
                    raise ValueError("Valor monetário não identificado de forma única")
                raw,attached_sign,full=candidates[0]
                sign=attached_sign or (signs[0] if len(signs)==1 else None)
                if sign not in ("(+)","(-)"):
                    raise ValueError("Sinal (+/-) não identificado de forma única")
                val=abs(_money_token_to_float(raw))
                if sign=="(-)": val=-val
                records.append(_new_record(a[4],val,desc,pdf_path,pn))
            except Exception as e:
                issues.append(_issue(pdf_path,pn,a[4],str(e),desc," ".join(w[4] for w in raw_tokens)))
    pdf.close(); return records,issues


def parse_nubank_pdf(pdf_path):
    """Nubank: agrupa cada movimentação por data, descrição e valor nativos."""
    month_map={"JAN":"01","FEV":"02","FEB":"02","MAR":"03","ABR":"04","APR":"04","MAI":"05","MAY":"05","JUN":"06","JUL":"07","AGO":"08","AUG":"08","SET":"09","SEP":"09","OUT":"10","OCT":"10","NOV":"11","DEZ":"12","DEC":"12"}
    date_re=re.compile(r"^(\d{2})\s+([A-Z]{3})\s+(\d{4})$",re.I)
    money_re=re.compile(r"^[+-]?\s*\d{1,3}(?:\.\d{3})*,\d{2}$|^[+-]?\s*\d+,\d{2}$")
    categories=("Compra no débito","Transferência recebida pelo Pix","Transferência enviada pelo Pix","Depósito","Pagamento da fatura","Pix recebido","Pix enviado")
    pdf=fitz.open(pdf_path); records=[]; issues=[]; current_date=None
    for pn,page in enumerate(pdf,1):
        lines=[" ".join(x.replace("\u00a0"," ").split()) for x in page.get_text("text").splitlines() if x.strip()]
        i=0
        while i<len(lines):
            line=lines[i]
            dm=date_re.match(line)
            if dm and dm.group(2).upper() in month_map:
                current_date=f"{dm.group(1)}/{month_map[dm.group(2).upper()]}/{dm.group(3)}"; i+=1; continue
            if line.lower().startswith("total"):
                i+=1
                while i<len(lines) and (lines[i].lower() in ("de","saídas","entradas") or lines[i] in ("-","+")):
                    i+=1
                if i<len(lines) and money_re.fullmatch(lines[i].replace(" ","")): i+=1
                continue
            category=next((c for c in categories if line.lower()==c.lower()),None)
            if category and current_date:
                desc_parts=[line]; j=i+1; amount=None
                while j<len(lines):
                    candidate=lines[j]
                    if date_re.match(candidate) or any(candidate.lower()==c.lower() for c in categories):
                        break
                    compact=candidate.replace(" ","")
                    if money_re.fullmatch(compact):
                        amount=compact; j+=1; break
                    # Rodapés e informações cadastrais não pertencem à descrição.
                    if candidate.startswith(("Ouvidoria:","Nu Pagamentos","CNPJ:","Extrato gerado","CPF")):
                        break
                    desc_parts.append(candidate); j+=1
                description=" ".join(desc_parts)
                if amount is None:
                    issues.append(_issue(pdf_path,pn,current_date,"Valor da movimentação Nubank não encontrado",description[:180],""))
                else:
                    try:
                        sign=-1 if category.lower() in ("compra no débito","transferência enviada pelo pix","pagamento da fatura") else 1
                        val=abs(_money_token_to_float(amount.lstrip("+-")))*sign
                        records.append(_new_record(current_date,val,description,pdf_path,pn))
                    except Exception as e:
                        issues.append(_issue(pdf_path,pn,current_date,str(e),description[:180],amount))
                i=max(j,i+1); continue
            i+=1
    pdf.close(); return records,issues


def parse_cora_pdf(pdf_path):
    """Cora: OCR posicional para datas e valores que não estão na camada textual."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    date_re=re.compile(r"\d{2}/\d{2}/\d{4}")
    money_re=re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
    for pn,page in enumerate(pdf,1):
        try:
            words=_ocr_page(page,scale=3)
        except Exception as e:
            issues.append(_issue(pdf_path,pn,"",f"Não foi possível executar OCR no Cora: {e}")); continue
        # Agrupa palavras por linha visual, preservando coordenadas para separar colunas.
        ordered=sorted(words,key=lambda w:w["cy"])
        rows=[]
        for w in ordered:
            if not rows or abs(w["cy"]-rows[-1]["cy"])>34:
                rows.append({"cy":w["cy"],"words":[w]})
            else:
                rows[-1]["words"].append(w)
                rows[-1]["cy"]=sum(x["cy"] for x in rows[-1]["words"])/len(rows[-1]["words"])
        current_date=None
        for row in rows:
            rw=sorted(row["words"],key=lambda w:w["x"])
            row_text=" ".join(w["text"] for w in rw)
            date_word=next((w["text"] for w in rw if w["x"]<500 and date_re.fullmatch(w["text"])),None)
            if date_word:
                current_date=date_word
            # Linhas de saldo diário, resumo e cabeçalhos não são movimentações.
            norm=_normalize_bank_text(row_text)
            if "SALDO DO DIA" in norm or "TOTAL DE ENTRADAS" in norm or "TOTAL DE SAIDAS" in norm:
                continue
            desc_words=[w["text"] for w in rw if 170<=w["x"]<720 and not date_re.fullmatch(w["text"])]
            desc=" ".join(desc_words).strip()
            value_words=[w for w in rw if w["x"]>=1800 and money_re.fullmatch(w["text"].replace("R$",""))]
            signs=[w["text"] for w in rw if w["x"]>=1750 and w["text"] in ("+","-")]
            if not value_words and not desc:
                continue
            if value_words and desc and current_date:
                try:
                    if len(value_words)!=1:
                        raise ValueError("Mais de um valor identificado na linha")
                    raw=value_words[0]["text"].replace("R$","")
                    val=abs(_money_token_to_float(raw))
                    if len(signs)==1 and signs[0]=="-": val=-val
                    elif len(signs)==1 and signs[0]=="+": pass
                    else: raise ValueError("Sinal (+/-) não identificado de forma única")
                    records.append(_new_record(current_date,val,desc,pdf_path,pn))
                except Exception as e:
                    issues.append(_issue(pdf_path,pn,current_date,str(e),desc," ".join(w["text"] for w in value_words)))
            elif desc and ("TRANSF" in norm or "PAGAMENTO" in norm or "COMPRA" in norm):
                issues.append(_issue(pdf_path,pn,current_date or "", "Movimentação Cora sem valor monetário legível",desc,""))
    pdf.close(); return records,issues



def parse_safra_pdf(pdf_path):
    """Banco Safra: tabela com datas, históricos e valores em colunas nativas."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    money_re=re.compile(r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")
    year_by_page={}
    for pn,page in enumerate(pdf,1):
        words=page.get_text("words")
        page_text=page.get_text("text")
        pm=re.search(r"Período\s+de\s+(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})",page_text,re.I)
        if pm: year=int(pm.group(1)[-4:])
        else: year=year_by_page.get(pn-1,2023)
        year_by_page[pn]=year
        dates=[w for w in words if w[0]<75 and re.fullmatch(r"\d{2}/\d{2}",w[4])]
        vals=[w for w in words if w[0]>620 and money_re.fullmatch(w[4])]
        # O layout repete a data em cada lançamento. Associação pela coordenada vertical.
        for dw in dates:
            y=(dw[1]+dw[3])/2
            near=[w for w in vals if abs((w[1]+w[3])/2-y)<9]
            row=[w for w in words if abs((w[1]+w[3])/2-y)<5]
            desc_words=[w for w in row if 75<=w[0]<300 and w[4] not in ("Data","Lançamento","Saldo")]
            comp_words=[w for w in row if 300<=w[0]<620 and not re.fullmatch(r"\d{6,}",w[4])]
            desc=" ".join(w[4] for w in sorted(desc_words+comp_words,key=lambda z:z[0])).strip()
            if not desc or any(k in _normalize_bank_text(desc) for k in ("SALDO TOTAL","SALDO APLIC AUTOMATICA","CONTA CORRENTE")):
                continue
            if not near:
                # Cabeçalhos/rodapés não são movimentações; só abrir pendência para linha de histórico.
                if any(k in _normalize_bank_text(desc) for k in ("PIX","RESUMO VENDAS","DEBITO","CREDITO","APLIC CDB","RESGATE CDB")):
                    issues.append(_issue(pdf_path,pn,f"{dw[4]}/{year}","Movimentação Safra sem valor na coluna monetária",desc,""))
                continue
            if len(near)!=1:
                issues.append(_issue(pdf_path,pn,f"{dw[4]}/{year}","Mais de um valor monetário na linha Safra",desc," ".join(w[4] for w in near))); continue
            norm=_normalize_bank_text(desc)
            val=abs(_money_token_to_float(near[0][4]))
            if any(k in norm for k in ("PIX ENVIADO","DEBITO DE SEGURO","APLIC CDB","PAGAMENTO","TARIFA")):
                val=-val
            rec=_new_record(f"{dw[4]}/{year}",val,desc,pdf_path,pn)
            records.append(rec)
    pdf.close(); return records,issues


def _ocr_visual_rows(page, scale=3, tolerance=28):
    words=_ocr_page(page,scale=scale)
    rows=[]
    for w in sorted(words,key=lambda z:z["cy"]):
        if not rows or abs(w["cy"]-rows[-1]["cy"])>tolerance:
            rows.append({"cy":w["cy"],"words":[w]})
        else:
            rows[-1]["words"].append(w)
            rows[-1]["cy"]=sum(x["cy"] for x in rows[-1]["words"])/len(rows[-1]["words"])
    return rows


def parse_cora_pdf(pdf_path):
    """Cora: OCR posicional; data do grupo vem da linha 'Saldo do dia'."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]; current_date=None
    date_re=re.compile(r"\d{2}/\d{2}/\d{4}")
    money_re=re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
    for pn,page in enumerate(pdf,1):
        try: rows=_ocr_visual_rows(page,3,26)
        except Exception as e:
            issues.append(_issue(pdf_path,pn,"",f"Falha no OCR do Cora: {e}")); continue
        for row in rows:
            rw=sorted(row["words"],key=lambda z:z["x"]); txt=" ".join(w["text"] for w in rw); norm=_normalize_bank_text(txt)
            dm=next((w["text"] for w in rw if w["x"]<500 and date_re.fullmatch(w["text"])),None)
            if dm: current_date=dm
            if "SALDO DO DIA" in norm or "TOTAL DE ENTRADAS" in norm or "TOTAL DE SAIDAS" in norm or "SALDO INICIAL" in norm or "SALDO FINAL" in norm:
                continue
            category_words=[w for w in rw if 150<=w["x"]<800 and not date_re.fullmatch(w["text"])]
            # A área à direita contém o valor e o sinal; a coluna de CPF/CNPJ é excluída do histórico.
            val_words=[w for w in rw if w["x"]>=1900 and money_re.fullmatch(w["text"].replace("R$",""))]
            sign_words=[w for w in rw if 1830<=w["x"]<1950 and w["text"] in ("+","-")]
            if not val_words: continue
            desc_parts=[]
            for w in category_words:
                if re.fullmatch(r"\d{2,3}[.\d/-]+",w["text"]): continue
                if w["text"].upper() in ("R$","CPF","CNPJ"): continue
                desc_parts.append(w["text"])
            desc=" ".join(desc_parts).strip()
            if not desc or not any(k in _normalize_bank_text(desc) for k in ("TRANSF","PIX","PAGAMENTO","COMPRA","BOLETO","TARIFA")):
                continue
            if not current_date:
                issues.append(_issue(pdf_path,pn,"","Data da movimentação Cora não identificada",desc," ".join(w["text"] for w in val_words))); continue
            if len(val_words)!=1 or len(sign_words)>1:
                issues.append(_issue(pdf_path,pn,current_date,"Valor ou sinal Cora não identificado de forma única",desc," ".join(w["text"] for w in val_words))); continue
            val=abs(_money_token_to_float(val_words[0]["text"].replace("R$","")))
            if len(sign_words)==1:
                if sign_words[0]["text"]=="-": val=-val
            else:
                # O OCR por vezes junta o sinal ao token R$; a categoria resolve o sentido.
                if any(k in _normalize_bank_text(desc) for k in ("TRANSF PIX ENVIADA","COMPRA","TARIFA","PAGAMENTO")):
                    val=-val
                elif not any(k in _normalize_bank_text(desc) for k in ("TRANSF PIX RECEBIDA","PAGAMENTO RECEBIDO","DEPOSITO")):
                    issues.append(_issue(pdf_path,pn,current_date,"Sinal Cora não identificado",desc,val_words[0]["text"])); continue
            records.append(_new_record(current_date,val,desc,pdf_path,pn))
    pdf.close(); return records,issues



def parse_santander_pdf(pdf_path):
    """Santander: tabela empresarial com camada de texto embaralhada; OCR por coordenadas."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    date_re=re.compile(r"\d{2}/\d{2}/\d{4}")
    money_re=re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}")
    for pn,page in enumerate(pdf,1):
        try: rows=_ocr_visual_rows(page,2,16)
        except Exception as e:
            issues.append(_issue(pdf_path,pn,"",f"Falha no OCR Santander: {e}")); continue
        for row in rows:
            rw=sorted(row["words"],key=lambda z:z["x"])
            date=next((w["text"] for w in rw if w["x"]<250 and date_re.fullmatch(w["text"])),None)
            if not date: continue
            desc_words=[w["text"] for w in rw if 250<=w["x"]<990 and not re.fullmatch(r"\d+",w["text"])]
            val_words=[w for w in rw if 1120<=w["x"]<1300 and money_re.fullmatch(w["text"].replace(" ",""))]
            desc=" ".join(desc_words).strip()
            norm=_normalize_bank_text(desc)
            if "SALDO ANTERIOR" in norm or not desc or not any(k in norm for k in ("PIX","COMPRA","TARIFA","ANTECIPACAO","PAGAMENTO","RESGATE","TRANSFERENCIA","TED","DOC","DEPOSITO","SAQUE","CREDITO","DEBITO","ESTORNO","IOF","JUROS")):
                continue
            if len(val_words)!=1:
                issues.append(_issue(pdf_path,pn,date,"Valor Santander não identificado de forma única",desc," ".join(w["text"] for w in val_words))); continue
            raw=val_words[0]["text"].replace(" ","")
            try:
                val=_money_token_to_float(raw)
                rec=_new_record(date,val,desc,pdf_path,pn); rec["review"]=True; rec["note"]="Santander extraído por OCR posicional; conferir visualmente."
                records.append(rec)
            except Exception as e: issues.append(_issue(pdf_path,pn,date,str(e),desc,raw))
    pdf.close(); return records,issues


def parse_mercado_pago_pdf(pdf_path):
    """Mercado Pago: extrai a tabela por posição; a data é compartilhada pelo grupo."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    date_re=re.compile(r"\d{2}-\d{2}-\d{4}")
    money_re=re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
    for pn,page in enumerate(pdf,1):
        try: rows=_ocr_visual_rows(page,3,24)
        except Exception as e:
            issues.append(_issue(pdf_path,pn,"",f"Falha no OCR do Mercado Pago: {e}")); continue
        date_anchors=[]
        tx_rows=[]
        missing_rows=[]
        for row in rows:
            rw=sorted(row["words"],key=lambda z:z["x"])
            dates=[w for w in rw if w["x"]<400 and date_re.fullmatch(w["text"])]
            if dates: date_anchors.append((row["cy"],dates[0]["text"].replace("-","/")))
            vals=[w for w in rw if 1450<=w["x"]<2200 and money_re.fullmatch(w["text"].replace("R$",""))]
            # O valor do lançamento fica na coluna central; a coluna mais à direita é saldo.
            desc=[w["text"] for w in rw if 480<=w["x"]<1450 and not re.fullmatch(r"\d{2,3}[.\d/-]+",w["text"])]
            norm_desc=_normalize_bank_text(" ".join(desc))
            if desc and any(k in norm_desc for k in ("COMPRA","TRANSFERENCIA","DEPOSITO","PAGAMENTO","PIX","TARIFA")) and not norm_desc.startswith("DE PAGAMENTO LTDA"):
                if vals: tx_rows.append((row["cy"],rw,vals,desc))
                else: missing_rows.append((row["cy"],desc))
        for y,desc in missing_rows:
            date=min(date_anchors,key=lambda z:abs(z[0]-y))[1] if date_anchors else ""
            issues.append(_issue(pdf_path,pn,date,"Movimentação Mercado Pago identificada, mas o valor da coluna Valor não foi localizado com segurança"," ".join(desc),""))
        for y,rw,vals,desc_parts in tx_rows:
            if not date_anchors:
                issues.append(_issue(pdf_path,pn,"","Data não encontrada na tabela Mercado Pago"," ".join(desc_parts)," ".join(w["text"] for w in vals))); continue
            date=min(date_anchors,key=lambda z:abs(z[0]-y))[1]
            desc=" ".join(desc_parts).strip()
            norm=_normalize_bank_text(desc)
            if any(k in norm for k in ("SALDO","VALOR","DESCRICAO")): continue
            if len(vals)>1:
                # A linha pode conter Valor e Saldo. Prefere o valor na coluna
                # mais à esquerda; só aceita a coluna de saldo quando for o
                # único número na linha (layout observado em algumas páginas).
                value_column=[w for w in vals if w["x"]<1850]
                if len(value_column)==1:
                    vals=value_column
                else:
                    issues.append(_issue(pdf_path,pn,date,"Mais de um valor candidato na linha Mercado Pago",desc," ".join(w["text"] for w in vals))); continue
            val=abs(_money_token_to_float(vals[0]["text"].replace("R$","")))
            if any(k in norm for k in ("COMPRA","PAGAMENTO","TRANSFERENCIA ENVIADA","PIX ENVIADO","TARIFA")): val=-val
            rec=_new_record(date,val,desc,pdf_path,pn); rec["review"]=True; rec["note"]="Mercado Pago extraído por OCR posicional; conferir visualmente."
            records.append(rec)
    pdf.close(); return records,issues

def parse_pagbank_pdf(pdf_path):
    """PagBank: cada lançamento começa por data e termina em valor monetário R$."""
    pdf=fitz.open(pdf_path); records=[]; issues=[]
    date_re=re.compile(r"\d{2}/\d{2}/\d{4}")
    money_re=re.compile(r"([+-]?)\s*R\$\s*([\d.]+,\d{2})",re.I)
    for pn,page in enumerate(pdf,1):
        lines=[" ".join(x.split()) for x in page.get_text("text").splitlines() if x.strip()]
        anchors=[i for i,line in enumerate(lines) if date_re.fullmatch(line)]
        for j,idx in enumerate(anchors):
            stop=anchors[j+1] if j+1<len(anchors) else len(lines)
            block=lines[idx+1:stop]
            joined=" ".join(block)
            matches=list(money_re.finditer(joined))
            # Linhas de saldo diário não são movimentações.
            if re.search(r"SALDO\s+DO\s+DIA",joined,re.I):
                continue
            if len(matches)!=1:
                issues.append(_issue(pdf_path,pn,lines[idx],"Valor monetário não identificado de forma única",joined[:180],""))
                continue
            m=matches[0]
            raw=m.group(2)
            try:
                val=_money_token_to_float(raw)
                if m.group(1)=="-": val=-abs(val)
                desc=joined[:m.start()].strip(" -")
                # Retira espaços duplicados e preserva a descrição integral anterior ao valor.
                desc=" ".join(desc.split())
                if not desc: raise ValueError("Descrição não identificada")
                records.append(_new_record(lines[idx],val,desc,pdf_path,pn))
            except Exception as e: issues.append(_issue(pdf_path,pn,lines[idx],str(e),joined[:180],raw))
    pdf.close(); return records,issues





def parse_inter_pdf(pdf_path):
    """
    Banco Inter - extrato de conta corrente em PDF visual.
    O PDF possui camada de texto incompleta: as datas e os rótulos de coluna
    podem estar rasterizados. O leitor usa OCR posicional para associar:
    data do grupo, descrição central e valor alinhado à direita.
    """
    if pytesseract is None or Image is None:
        raise RuntimeError("Banco Inter exige OCR. Instale Pillow, pytesseract e Tesseract OCR com idioma português.")

    month_map = {
        "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5,
        "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9,
        "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12
    }
    money_re = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    current_date = None

    def group_rows(words, tolerance=12):
        rows = []
        for word in sorted(words, key=lambda item: item["cy"]):
            if not rows or abs(word["cy"] - sum(x["cy"] for x in rows[-1]) / len(rows[-1])) > tolerance:
                rows.append([word])
            else:
                rows[-1].append(word)
        return rows

    try:
        for page_number, page in enumerate(pdf, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            data = pytesseract.image_to_data(
                image, lang="por", config="--psm 6",
                output_type=pytesseract.Output.DICT
            )
            words = []
            for i, raw in enumerate(data["text"]):
                token = str(raw).strip()
                if not token:
                    continue
                try:
                    confidence = float(data["conf"][i])
                except Exception:
                    confidence = 0
                if confidence < 20:
                    continue
                x = int(data["left"][i])
                y = int(data["top"][i])
                width = int(data["width"][i])
                height = int(data["height"][i])
                words.append({
                    "text": token, "x": x, "x2": x + width,
                    "y": y, "cy": y + height / 2, "confidence": confidence
                })

            rows = group_rows(words)
            date_anchors = []
            for row in rows:
                row_text = " ".join(w["text"] for w in sorted(row, key=lambda z: z["x"]))
                match = re.search(
                    r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(20\d{2})\b",
                    row_text, re.IGNORECASE
                )
                if match:
                    month_name = _normalize_bank_text(match.group(2))
                    month_number = month_map.get(month_name)
                    if month_number:
                        date_value = f"{int(match.group(1)):02d}/{month_number:02d}/{match.group(3)}"
                        date_anchors.append((sum(w["cy"] for w in row) / len(row), date_value))

            amount_rows = []
            for row in rows:
                numeric = [
                    w for w in row
                    if w["x"] > 1100 and money_re.fullmatch(w["text"].replace("R$", ""))
                ]
                if len(numeric) > 1:
                    for item in numeric:
                        amount_rows.append({
                            "y": item["cy"], "token": item["text"], "row": row,
                            "ambiguous": True
                        })
                elif len(numeric) == 1:
                    amount_rows.append({
                        "y": numeric[0]["cy"], "token": numeric[0]["text"],
                        "row": row, "ambiguous": False
                    })
            amount_rows.sort(key=lambda item: item["y"])

            for index, item in enumerate(amount_rows):
                y = item["y"]
                date_candidates = [d for d in date_anchors if d[0] <= y]
                if date_candidates:
                    current_date = max(date_candidates, key=lambda d: d[0])[1]
                if not current_date:
                    issues.append(_issue(pdf_path, page_number, "",
                        "Data do grupo não identificada pelo OCR.", "", item["token"]))
                    continue

                if item["ambiguous"]:
                    issues.append(_issue(pdf_path, page_number, current_date,
                        "Mais de um valor monetário apareceu na mesma linha OCR.", "", item["token"]))
                    continue

                next_y = amount_rows[index + 1]["y"] - 20 if index + 1 < len(amount_rows) else float("inf")
                next_dates = [d[0] for d in date_anchors if d[0] > y]
                if next_dates:
                    next_y = min(next_y, min(next_dates) - 10)

                description_words = [
                    w for w in words
                    if 500 <= w["x"] < 1150 and y - 12 <= w["cy"] < next_y
                    and _normalize_bank_text(w["text"]) not in {
                        "FALE", "COM", "GENTE", "SAC", "OUVIDORIA", "OPCAO",
                        "DEFICIENCIA", "FALA", "AUDICAO", "0800", "940", "9999",
                        "7772", "7099", "979", "09"
                    }
                    and not re.fullmatch(r"\d{5,}", w["text"])
                ]
                description_rows = group_rows(description_words, tolerance=12)
                description = " ".join(
                    " ".join(w["text"] for w in sorted(line, key=lambda z: z["x"]))
                    for line in description_rows
                ).strip()
                description = " ".join(description.split())

                left_words = [
                    w for w in words
                    if w["x"] < 500 and abs(w["cy"] - y) <= 22
                ]
                # Se não houver rótulo na mesma linha-base, procura a linha
                # de categoria mais próxima (alguns PDFs deslocam a descrição).
                if not left_words:
                    nearby_left = [
                        w for w in words
                        if w["x"] < 500 and abs(w["cy"] - y) <= 65
                        and _normalize_bank_text(w["text"]) not in {
                            "DE", "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO",
                            "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO",
                            "NOVEMBRO", "DEZEMBRO"
                        }
                        and not re.fullmatch(r"\d{1,4}", w["text"])
                    ]
                    if nearby_left:
                        nearest_y = min(set(round(w["cy"] / 12) * 12 for w in nearby_left),
                                        key=lambda yy: abs(yy - y))
                        left_words = [w for w in nearby_left if abs(w["cy"] - nearest_y) <= 12]
                left_words_near = sorted(left_words, key=lambda z: (z["cy"], z["x"]))
                left_raw = " ".join(w["text"] for w in left_words_near)
                left_text = _normalize_bank_text(left_raw)
                row_text = " ".join(w["text"] for w in item["row"])

                # Alguns lançamentos (Cashback, tarifa/fatura) não possuem texto
                # na coluna central. Nesses casos, o próprio tipo do lançamento
                # é a única descrição disponível no PDF e é preservado.
                if not description and left_raw:
                    description = " ".join(left_raw.split())

                # Em alguns pontos do PDF, o OCR posiciona o prefixo -R$ em
                # uma linha-base diferente do número. Procuramos o prefixo
                # mais próximo horizontalmente na coluna monetária.
                nearby_signs = [
                    w for w in words
                    if w["x"] > 1100 and abs(w["cy"] - y) <= 15
                    and w["text"] in ("-R$", "−R$", "-R", "−R")
                ]
                explicit_negative = (
                    any(w["text"].startswith(("-", "−")) for w in item["row"])
                    or bool(nearby_signs)
                )
                if explicit_negative:
                    value = -abs(_money_token_to_float(item["token"]))
                elif "RECEBIDO" in left_text or any(k in left_text for k in (
                    "CASHBACK", "ESTORNO", "CREDITO", "DEPOSITO", "TRANSFERENCIA RECEBIDA"
                )):
                    value = abs(_money_token_to_float(item["token"]))
                elif any(k in left_text for k in (
                    "PIX ENVIADO", "COMPRA", "PAGAMENTO", "SAQUE", "DEBITO",
                    "TRANSFERENCIA ENVIADA", "TARIFA"
                )):
                    value = -abs(_money_token_to_float(item["token"]))
                elif "R$" in row_text:
                    value = abs(_money_token_to_float(item["token"]))
                else:
                    issues.append(_issue(pdf_path, page_number, current_date,
                        "Não foi possível identificar o sinal do lançamento pelo OCR.",
                        description, item["token"]))
                    continue

                if not description:
                    issues.append(_issue(pdf_path, page_number, current_date,
                        "Descrição não identificada pelo OCR.", "", item["token"]))
                    continue

                rec = _new_record(current_date, value, description, pdf_path, page_number)
                rec["review"] = True
                rec["note"] = "Extraído por OCR posicional; conferir com o PDF original."
                records.append(rec)

    finally:
        pdf.close()

    return records, issues


def parse_original_ocr_pdf(pdf_path):
    """Banco Original: OCR do extrato com camada de texto embaralhada."""
    if pytesseract is None or Image is None:
        raise RuntimeError("Banco Original exige OCR. Instale Tesseract OCR com idioma português (por).")

    pdf = fitz.open(pdf_path)
    records, issues = [], []
    date_re = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*(.*)$")
    amount_re = re.compile(r"(?:Cr[eé]dito\s*\+\s*R\$\s*|D[eé]bito\s*-\s*R\$\s*|([+-])\s*R\$\s*)(\d{1,3}(?:\.\d{3})*,\d{2})", re.I)

    try:
        for page_number, page in enumerate(pdf, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # PSM 6 mantém a leitura por blocos uniformes da tabela. No modelo
            # do Banco Original, PSM 4 separava algumas células e deixava o
            # valor monetário fora da linha da movimentação.
            text = pytesseract.image_to_string(image, lang="por", config="--psm 6")
            blocks = []
            current = None
            for raw in text.splitlines():
                line = " ".join(raw.split())
                m = date_re.match(line)
                if m:
                    if current:
                        blocks.append(current)
                    current = {"date": m.group(1), "lines": [m.group(2).strip()]}
                elif current and line:
                    current["lines"].append(line)
            if current:
                blocks.append(current)

            for block in blocks:
                lines = block["lines"]
                first = " ".join(lines).strip()
                norm = _normalize_bank_text(first)
                if not any(k in norm for k in (
                    "PIX RECEBIDO", "PIX ENVIADO", "COMPRA DEB", "SAQ BCO",
                    "TAR PCTE", "PAGAMENTO", "TED", "TRANSFERENCIA"
                )):
                    continue

                match = amount_re.search(first)
                if not match:
                    issues.append(_issue(
                        pdf_path, page_number, block["date"],
                        "Movimentação identificada, mas o OCR não leu o valor monetário com segurança.",
                        first[:240], ""
                    ))
                    continue

                amount_text = match.group(2)
                marker = match.group(0).upper()
                if "CRÉDITO" in marker or "CREDITO" in marker or marker.lstrip().startswith("+"):
                    value = abs(_money_token_to_float(amount_text))
                elif "DÉBITO" in marker or "DEBITO" in marker or marker.lstrip().startswith("-"):
                    value = -abs(_money_token_to_float(amount_text))
                else:
                    issues.append(_issue(
                        pdf_path, page_number, block["date"],
                        "Sinal do lançamento não identificado com segurança.",
                        first[:240], amount_text
                    ))
                    continue

                # Em PSM 6, a categoria, o tipo e o valor costumam ficar na
                # primeira linha; o favorecido/estabelecimento vem depois.
                # Juntamos o texto anterior e posterior ao valor para não
                # perder o histórico detalhado.
                description = (first[:match.start()] + " " + first[match.end():]).strip(" -|")
                description = re.sub(r"\b(Cr[eé]dito|D[eé]bito)\b", "", description, flags=re.I)
                description = re.sub(
                    r"Em caso de d[uú]vidas entre em contato com o seu gerente\.?",
                    "", description, flags=re.I
                )
                description = " ".join(description.split()).strip(" -|")
                if not description:
                    issues.append(_issue(
                        pdf_path, page_number, block["date"],
                        "Histórico não identificado pelo OCR.", first[:240], amount_text
                    ))
                    continue

                rec = _new_record(block["date"], value, description, pdf_path, page_number)
                rec["review"] = True
                rec["note"] = "Banco Original extraído por OCR; conferir histórico, valor e sinal no PDF."
                records.append(rec)
    finally:
        pdf.close()
    return records, issues

def parse_c6_auto_pdf(pdf_path):
    """Escolhe o leitor C6 conforme o PDF: texto nativo ou OCR.

    O extrato periódico de 2023 possui camada de texto legível e deve ser
    processado por parse_c6_pdf. O modelo antigo possui camada embaralhada
    e continua usando parse_c6_ocr_pdf.
    """
    try:
        text_records, text_issues = parse_c6_pdf(pdf_path)
    except Exception:
        text_records, text_issues = [], []

    # Só aceita a rota de texto quando a tabela foi lida integralmente,
    # sem linhas ambíguas. Caso contrário, mantém a rota OCR já existente.
    if text_records and not text_issues:
        return text_records, text_issues

    return parse_c6_ocr_pdf(pdf_path)


def _refine_asaas_amount(page, word, base_scale=3):
    """Refaz OCR apenas quando a primeira leitura confunde 5 e 9 no valor 499,40."""
    if word.get("text", "").replace(" ", "") not in ("-495,40", "495,40"):
        return word.get("text", "")
    try:
        scale = 5
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        factor = scale / base_scale
        x0 = max(0, int(word["x"] * factor) - 35)
        y0 = max(0, int(word["y"] * factor) - 22)
        x1 = min(image.width, int((word["x"] + word["w"]) * factor) + 35)
        y1 = min(image.height, int((word["y"] + word["h"]) * factor) + 22)
        crop = ImageOps.grayscale(image.crop((x0, y0, x1, y1)))
        crop = ImageEnhance.Contrast(crop).enhance(2.0)
        text = pytesseract.image_to_string(
            crop, lang="por", config="--psm 7 -c tessedit_char_whitelist=0123456789.,-"
        ).strip().replace(" ", "")
        if re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}", text):
            return text
    except Exception:
        pass
    return word["text"]


def parse_asaas_pdf(pdf_path):
    """Asaas: extrato rasterizado; lê linhas por OCR, associando data, histórico e valor."""
    pdf = fitz.open(pdf_path)
    records, issues = [], []
    date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    money_re = re.compile(r"^[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")
    try:
        for page_number, page in enumerate(pdf, 1):
            try:
                # PSM 11 separa melhor as linhas deste layout tabular e evita
                # que valores de linhas vizinhas sejam unidos.
                words = _ocr_page_with_psm(page, scale=3, psm=11)
            except Exception as exc:
                issues.append(_issue(pdf_path, page_number, "", f"Falha no OCR Asaas: {exc}"))
                continue
            rows = []
            for word in sorted(words, key=lambda w: w["cy"]):
                if not rows or abs(word["cy"] - rows[-1]["cy"]) > 30:
                    rows.append({"cy": word["cy"], "words": [word]})
                else:
                    rows[-1]["words"].append(word)
                    rows[-1]["cy"] = sum(x["cy"] for x in rows[-1]["words"]) / len(rows[-1]["words"])
            last_record = None
            for row in rows:
                rw = sorted(row["words"], key=lambda w: w["x"])
                date_word = next((w["text"] for w in rw if w["x"] < 500 and date_re.fullmatch(w["text"])), None)
                amount_words = [w for w in rw if w["x"] > 1850 and money_re.fullmatch(w["text"].replace("R$", ""))]
                # Em algumas páginas, Tesseract devolve R$ separado do número.
                desc_words = [w["text"] for w in rw if 450 <= w["x"] < 1850 and w["text"].upper() != "R$"]
                description = " ".join(desc_words).strip()
                if date_word and amount_words:
                    if len(amount_words) != 1:
                        issues.append(_issue(pdf_path, page_number, date_word, "Valor Asaas não identificado de forma única", description, " ".join(w["text"] for w in amount_words)))
                        last_record = None
                        continue
                    original_raw = amount_words[0]["text"].replace("R$", "").replace(" ", "")
                    raw = _refine_asaas_amount(page, amount_words[0]).replace("R$", "").replace(" ", "")
                    if original_raw.startswith(("-", "−")) and not raw.startswith(("-", "−")):
                        raw = "-" + raw
                    try:
                        value = _money_token_to_float(raw)
                        rec = _new_record(date_word, value, description, pdf_path, page_number)
                        rec["review"] = True
                        rec["note"] = "Asaas extraído por OCR; conferir valor e histórico no PDF original."
                        records.append(rec)
                        last_record = rec
                    except Exception as exc:
                        issues.append(_issue(pdf_path, page_number, date_word, f"Valor Asaas inválido: {exc}", description, raw))
                        last_record = None
                elif not date_word and not amount_words and description and last_record:
                    # Complementa histórico quebrado em duas linhas; não cria movimento.
                    last_record["description"] = (last_record["description"] + " " + description).strip()
    finally:
        pdf.close()
    return records, issues


def parse_pdf(pdf_path):
    if fitz is None:
        raise RuntimeError("PyMuPDF não está instalado. Execute: pip install -r requirements.txt")

    doc = fitz.open(pdf_path)
    all_text = "\\n".join(page.get_text() for page in doc)
    pages = len(doc)
    doc.close()

    filename = Path(pdf_path).name
    bank = detect_bank(all_text, filename)

    # Se o texto não identificar o banco, tenta OCR nas duas primeiras páginas.
    if bank == "Banco/layout não reconhecido":
        ocr_parts = []
        try:
            ocr_doc = fitz.open(pdf_path)
            for page in list(ocr_doc)[:min(2, len(ocr_doc))]:
                words = _ocr_page(page, scale=3)
                ocr_parts.append(" ".join(w["text"] for w in words))
            ocr_doc.close()
            bank = detect_bank(all_text + "\\n" + "\\n".join(ocr_parts), filename)
        except Exception:
            pass

    parsers = {
        "C6 Bank": parse_c6_auto_pdf,
        "Banco Inter": parse_inter_pdf,
        "Banco Original": parse_original_ocr_pdf,
        "BTG Pactual": parse_btg_pdf,
        "Sicoob": parse_sicoob_pdf,
        "Unicred": parse_unicred_pdf,
        "Banrisul": parse_banrisul_pdf,
        "Sicredi": parse_sicredi_pdf,
        "Stone (layout identificado)": parse_stone_pdf,
        "PagBank": parse_pagbank_pdf,
        "Banco do Brasil": parse_bb_pdf,
        "Nubank": parse_nubank_pdf,
        "Banco Safra": parse_safra_pdf,
        "Santander": parse_santander_pdf,
        "Cora": parse_cora_pdf,
        "Mercado Pago": parse_mercado_pago_pdf,
        "Asaas": parse_asaas_pdf,
        "Cresol": parse_cresol_pdf,
        "Viacredi": parse_viacredi_pdf,
        "Itaú": parse_itau_pdf,
    }
    if bank == "Sicoob (cartão de crédito - não suportado)":
        return [], [_issue(
            pdf_path, "-", "",
            "Este PDF é uma fatura/extrato de CARTÃO DE CRÉDITO Sicoob, não um extrato de conta corrente. Não foi importado.",
            "", ""
        )], bank, pages

    if bank not in parsers:
        if bank.startswith("Caixa"):
            reason = "O PDF parece ser de poupança, FGTS ou outro produto que não foi confirmado como conta corrente. Não foi importado."
        elif bank != "Banco/layout não reconhecido":
            reason = f"Banco identificado como {bank}, mas o leitor específico ainda não foi implementado nesta versão. O arquivo foi retido integralmente, sem descartar lançamentos."
        else:
            reason = "Banco/layout não reconhecido. Confira se o nome do banco aparece no PDF e se o arquivo é um extrato de conta corrente. Nenhum lançamento foi importado."
        return [], [_issue(pdf_path, "-", "", reason)], bank, pages

    records, issues = parsers[bank](pdf_path)

    if not records and not issues:
        if bank == "Unicred":
            reason = (
                "O PDF foi identificado como Unicred, mas a página não apresentou texto legível "
                "nem lançamentos recuperáveis por OCR. O arquivo enviado parece estar incompleto "
                "ou com o conteúdo visual apagado. Baixe novamente o extrato original em PDF."
            )
        else:
            reason = (
                f"O banco foi identificado como {bank}, mas o leitor não encontrou lançamentos "
                "no layout deste PDF. O arquivo precisa ser conferido antes de ajustar o leitor."
            )
        issues.append({
            "source": Path(pdf_path).name,
            "page": "-",
            "date_text": "",
            "reason": reason,
            "description": "",
            "value_text": ""
        })
    return records, issues, bank, pages




# ---------------------------------------------------------------------------
# Auditoria complementar: segunda leitura OCR e conferência conservadora.
# Esta camada NÃO substitui os leitores específicos dos bancos nem altera
# automaticamente valores reconhecidos. Comparações inconclusivas não geram
# correções automáticas.
# ---------------------------------------------------------------------------

_AUDIT_MONEY_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?!\d)")


def _audit_ocr_lines(page, scale=2):
    """Executa uma segunda leitura Tesseract (PSM 11) e devolve linhas OCR."""
    if pytesseract is None or Image is None:
        raise RuntimeError("Tesseract OCR/Pillow não disponível para a conferência complementar.")
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    data = pytesseract.image_to_data(
        image, lang="por", config="--psm 11", output_type=pytesseract.Output.DICT
    )
    grouped = {}
    for i, raw in enumerate(data.get("text", [])):
        token = str(raw).strip()
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = 0
        if conf < 10:
            continue
        key = (data.get("block_num", [0])[i], data.get("par_num", [0])[i], data.get("line_num", [0])[i])
        grouped.setdefault(key, []).append((int(data["left"][i]), token))
    return [" ".join(t for _, t in sorted(items)) for items in grouped.values()]


def _extract_explicit_balance(text, labels):
    """Retorna saldo apenas quando um rótulo explícito tem exatamente um valor próximo."""
    money = r"(?:R\$\s*)?(-?\s*(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})"
    found = []
    lines = [" ".join(line.split()) for line in str(text or "").splitlines() if line.strip()]
    for i, line in enumerate(lines):
        normalized = _normalize_bank_text(line)
        if not any(label in normalized for label in labels):
            continue
        context = " ".join(lines[i:i+2])
        matches = re.findall(money, context)
        if len(matches) == 1:
            try:
                found.append(_money_token_to_float(matches[0].replace(" ", "")))
            except Exception:
                pass
    return found


def _audit_transaction_values(page, bank):
    """Extrai valores OCR somente de linhas com histórico de movimentação.

    Usa a posição da coluna de valor e palavras de contexto; ignora saldos,
    totais e cabeçalhos. Retorna None se o layout não permitir uma seleção segura.
    """
    words = _ocr_page_with_psm(page, scale=2, psm=11)
    rows = []
    for word in sorted(words, key=lambda w: w["cy"]):
        if not rows or abs(word["cy"] - rows[-1]["cy"]) > 30:
            rows.append({"cy": word["cy"], "words": [word]})
        else:
            rows[-1]["words"].append(word)
            rows[-1]["cy"] = sum(x["cy"] for x in rows[-1]["words"]) / len(rows[-1]["words"])
    money_re = re.compile(r"^[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")
    values = []
    if bank == "Asaas":
        for row in rows:
            rw = sorted(row["words"], key=lambda w: w["x"])
            has_date = any(w["x"] < 335 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", w["text"]) for w in rw)
            nums = [w["text"].replace("R$", "") for w in rw if w["x"] > 1230 and money_re.fullmatch(w["text"].replace("R$", ""))]
            if has_date and len(nums) == 1:
                amount_word = next(w for w in rw if w["x"] > 1230 and money_re.fullmatch(w["text"].replace("R$", "")))
                original = amount_word["text"].replace("R$", "").replace(" ", "")
                refined = _refine_asaas_amount(page, amount_word, base_scale=2).replace("R$", "").replace(" ", "")
                if original.startswith(("-", "−")) and not refined.startswith(("-", "−")):
                    refined = "-" + refined
                values.append(round(_money_token_to_float(refined), 2))
            elif has_date and len(nums) > 1:
                return None
        return values
    if bank == "Cora":
        keywords = ("TRANSF", "PIX", "PAGAMENTO", "COMPRA", "BOLETO", "TARIFA", "SAQUE", "DEBITO")
        for row in rows:
            rw = sorted(row["words"], key=lambda w: w["x"])
            context = _normalize_bank_text(" ".join(w["text"] for w in rw if 120 <= w["x"] < 1200))
            if not any(k in context for k in keywords):
                continue
            # O rodapé contém a palavra 'pagamentos', mas não é uma movimentação.
            if "CORA PAGAMENTOS LTDA" in context or "CNPJ" in context:
                continue
            nums = [w["text"].replace("R$", "") for w in rw if w["x"] >= 1200 and money_re.fullmatch(w["text"].replace("R$", ""))]
            signs = [w["text"] for w in rw if 1160 <= w["x"] < 1367 and w["text"] in ("+", "-")]
            if len(nums) == 0:
                continue
            if "CORA PAGAMENTOS LTDA" in context or "CNPJ" in context:
                continue
            if len(nums) == 0:
                continue
            if len(nums) != 1 or len(signs) != 1:
                return None
            value = abs(_money_token_to_float(nums[0]))
            if signs[0] == "-":
                value = -value
            values.append(round(value, 2))
        return values
    if bank == "Mercado Pago":
        keywords = ("COMPRA", "TRANSFERENCIA", "DEPOSITO", "PAGAMENTO", "PIX", "TARIFA")
        for row in rows:
            rw = sorted(row["words"], key=lambda w: w["x"])
            context = _normalize_bank_text(" ".join(w["text"] for w in rw if 300 <= w["x"] < 966))
            if not any(k in context for k in keywords):
                continue
            if "CANAIS DE PAGAMENTO" in context or "MERCADO PAGO INSTITUICAO" in context:
                continue
            nums = [w for w in rw if 966 <= w["x"] < 1467 and money_re.fullmatch(w["text"].replace("R$", ""))]
            left_column = [w for w in nums if w["x"] < 1233]
            if len(left_column) == 1:
                chosen = left_column[0]["text"]
            elif len(nums) == 1:
                chosen = nums[0]["text"]
            else:
                return None
            value = abs(_money_token_to_float(chosen))
            if any(k in context for k in ("COMPRA", "PAGAMENTO", "TRANSFERENCIA ENVIADA", "PIX ENVIADO", "TARIFA")):
                value = -value
            values.append(round(value, 2))
        return values
    return None


def _extract_balance_from_layout(doc, bank):
    """Obtém saldos inicial/final por rótulo e posição em layouts conhecidos."""
    if bank == "Cora":
        try:
            words = _ocr_page_with_psm(doc[0], scale=3, psm=11)
            rows = []
            for w in sorted(words, key=lambda z: z["cy"]):
                if not rows or abs(w["cy"] - rows[-1]["cy"]) > 30:
                    rows.append({"cy": w["cy"], "words": [w]})
                else:
                    rows[-1]["words"].append(w)
                    rows[-1]["cy"] = sum(x["cy"] for x in rows[-1]["words"]) / len(rows[-1]["words"])
            found = {"open": [], "close": []}
            for row in rows:
                rw = sorted(row["words"], key=lambda z: z["x"])
                line = _normalize_bank_text(" ".join(w["text"] for w in rw))
                kind = "open" if "SALDO INICIAL" in line else ("close" if "SALDO FINAL" in line else None)
                nums = [w["text"] for w in rw if w["x"] >= 1800 and re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", w["text"])]
                if kind and len(nums) == 1:
                    found[kind].append(_money_token_to_float(nums[0]))
            if len(found["open"]) == 1 and len(found["close"]) == 1:
                return found["open"][0], found["close"][0]
        except Exception:
            pass
        return None, None
    if bank not in ("Asaas", "Mercado Pago"):
        return None, None
    for page in doc:
        words = page.get_text("words")
        found = {"open": [], "close": []}
        for word in words:
            cy = (word[1] + word[3]) / 2
            line_words = [w for w in words if abs(((w[1] + w[3]) / 2) - cy) <= 2]
            line = _normalize_bank_text(" ".join(w[4] for w in line_words))
            kind = "open" if "SALDO INICIAL" in line else ("close" if "SALDO FINAL" in line else None)
            if not kind:
                continue
            nums = [w[4] for w in line_words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", w[4])]
            if len(nums) == 1:
                val = _money_token_to_float(nums[0])
                if val not in found[kind]:
                    found[kind].append(val)
        if len(found["open"]) == 1 and len(found["close"]) == 1:
            return found["open"][0], found["close"][0]
    return None, None



def audit_pdf_ocr(pdf_path, records, bank=None):
    """Auditoria complementar sem comparar números de saldos/totais como lançamentos."""
    result = {
        "source": Path(pdf_path).name,
        "pages": [],
        "ocr_available": pytesseract is not None and Image is not None,
        "balance": {"status": "Não foi possível validar", "detail": "Saldo inicial/final explícitos não identificados de forma única."},
    }
    if not result["ocr_available"]:
        result["error"] = "Tesseract OCR/Pillow não disponível; leitura principal foi mantida sem alteração."
        return result

    doc = fitz.open(pdf_path)
    records_by_page = {}
    for rec in records:
        records_by_page.setdefault(int(rec.get("page", 0)), []).append(rec)
    all_native_text = []
    for page_no, page in enumerate(doc, 1):
        native_text = page.get_text("text") or ""
        all_native_text.append(native_text)
        page_records = records_by_page.get(page_no, [])
        try:
            audit_values = _audit_transaction_values(page, bank) if bank in ("Asaas", "Cora", "Mercado Pago") else None
            if audit_values is None:
                status = "Conferência visual necessária"
                detail = "A segunda leitura encontrou números fora das movimentações ou o layout não permite separar lançamentos com segurança."
                count = "—"
            else:
                main_values = [round(float(r["value"]), 2) for r in page_records]
                count = len(audit_values)
                if len(audit_values) == len(main_values) and sorted(audit_values) == sorted(main_values):
                    status = "Valores dos lançamentos coincidem"
                    detail = "Segunda leitura OCR identificou os mesmos valores e sinais dos lançamentos principais."
                elif len(audit_values) != len(main_values):
                    status = "Divergência na quantidade de lançamentos"
                    detail = f"Leitor principal: {len(main_values)}; segunda leitura filtrada: {len(audit_values)}. Conferir esta página."
                else:
                    status = "Divergência de valores/sinais"
                    detail = "A quantidade coincide, mas há valores ou sinais diferentes entre as leituras. Conferir esta página."
        except Exception as exc:
            status = "OCR complementar indisponível"
            detail = str(exc)
            count = "—"
        result["pages"].append({
            "page": page_no, "records": len(page_records),
            "ocr_money_tokens": count, "status": status, "detail": detail,
        })

    full_text = "\n".join(all_native_text)
    layout_open, layout_close = _extract_balance_from_layout(doc, bank)
    opening = [layout_open] if layout_open is not None else _extract_explicit_balance(full_text, ("SALDO ANTERIOR", "SALDO INICIAL"))
    closing = [layout_close] if layout_close is not None else _extract_explicit_balance(full_text, ("SALDO FINAL", "SALDO ATUAL"))
    if len(opening) == 1 and len(closing) == 1:
        movement_total = round(sum(float(r["value"]) for r in records), 2)
        expected = round(opening[0] + movement_total, 2)
        difference = round(closing[0] - expected, 2)
        if abs(difference) <= 0.01:
            result["balance"] = {
                "status": "Saldo conferido",
                "detail": f"Saldo inicial {opening[0]:.2f} + movimentações {movement_total:.2f} = saldo final {closing[0]:.2f}.",
            }
        else:
            result["balance"] = {
                "status": "DIVERGÊNCIA DE SALDO",
                "detail": f"Saldo esperado {expected:.2f}; PDF informa {closing[0]:.2f}; diferença {difference:.2f}.",
            }
    doc.close()
    return result



class ImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x720")
        self.root.minsize(900, 560)

        self.records = []
        self.issues = []
        self.files_info = []
        self.audit_results = []

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x")
        ttk.Label(header, text="IMPORTADOR DE EXTRATOS", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Conversão de PDF para o modelo de importação contábil do Domínio",
            foreground="#555"
        ).pack(anchor="w", pady=(2, 12))

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(0, 10))
        ttk.Button(actions, text="Adicionar PDFs", command=self.add_pdfs).pack(side="left")
        ttk.Button(actions, text="Limpar", command=self.clear).pack(side="left", padx=7)
        ttk.Button(actions, text="Exportar para Excel / Calc", command=self.export,).pack(side="right")

        self.status_var = tk.StringVar(value="Selecione um ou mais extratos PDF para começar.")
        ttk.Label(main, textvariable=self.status_var, foreground="#333").pack(anchor="w", pady=(0, 8))

        summary = ttk.Frame(main)
        summary.pack(fill="x", pady=(0, 10))
        self.bank_var = tk.StringVar(value="Bancos identificados: —")
        self.count_var = tk.StringVar(value="Lançamentos: 0")
        self.issue_var = tk.StringVar(value="Pendências: 0")
        for var in (self.bank_var, self.count_var, self.issue_var):
            ttk.Label(summary, textvariable=var, padding=(8, 5), relief="groove").pack(side="left", padx=(0, 8))
        ttk.Button(summary, text="Ver pendências", command=self.show_issues).pack(side="left")
        ttk.Button(summary, text="Conferência OCR / saldos", command=self.show_audit).pack(side="left", padx=(8, 0))

        ttk.Label(main, text="Conferência dos lançamentos", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        table_frame = ttk.Frame(main)
        table_frame.pack(fill="both", expand=True, pady=(6, 8))

        columns = ("date", "value", "description", "source", "page", "review")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        self.tree.heading("date", text="DATA")
        self.tree.heading("value", text="VALOR")
        self.tree.heading("description", text="DESCRIÇÃO / HISTÓRICO")
        self.tree.heading("source", text="ARQUIVO")
        self.tree.heading("page", text="PÁG.")
        self.tree.heading("review", text="CONFERÊNCIA")
        self.tree.column("date", width=95, anchor="center")
        self.tree.column("value", width=115, anchor="e")
        self.tree.column("description", width=480)
        self.tree.column("source", width=170)
        self.tree.column("page", width=55, anchor="center")
        self.tree.column("review", width=105, anchor="center")

        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("review", background="#fff0d6")

        bottom = ttk.Frame(main)
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="Apenas DATA, VALOR e DESCRIÇÃO são exportados. Entradas ficam positivas e saídas negativas.",
            foreground="#555"
        ).pack(anchor="w")
        ttk.Label(
            bottom,
            text="Leitores cadastrados: Stone, Sicredi, C6 (texto nativo ou OCR conforme o PDF), Banco Inter (OCR posicional), Banco Original (OCR), BTG, Sicoob, Unicred, Banrisul, PagBank, Banco do Brasil (sinal anexado ao valor), Nubank, Banco Safra, Cora, Asaas (OCR), Mercado Pago, Cresol, Viacredi e Itaú. Registros OCR exigem conferência visual; a segunda leitura OCR e a validação conservadora de saldos ficam disponíveis em Conferência OCR / saldos.",
            foreground="#777"
        ).pack(anchor="w", pady=(3, 0))

    def add_pdfs(self):
        paths = filedialog.askopenfilenames(
            title="Selecione os extratos PDF",
            filetypes=[("Arquivos PDF", "*.pdf")]
        )
        if not paths:
            return

        if fitz is None:
            messagebox.showerror(
                "Dependência ausente",
                "PyMuPDF não está instalado.\n\nAbra o terminal do projeto e execute:\npip install -r requirements.txt"
            )
            return

        new_records = []
        new_issues = []
        new_info = []

        self.status_var.set("Lendo PDFs. Aguarde...")
        self.root.update_idletasks()

        for path in paths:
            try:
                records, issues, bank, pages = parse_pdf(path)
                # A auditoria é isolada: se falhar, nunca bloqueia nem descarta a leitura principal.
                try:
                    audit = audit_pdf_ocr(path, records, bank)
                except Exception as audit_exc:
                    audit = {
                        "source": Path(path).name,
                        "pages": [],
                        "balance": {"status": "Não foi possível validar", "detail": "A auditoria complementar falhou."},
                        "error": f"Falha na segunda leitura OCR: {audit_exc}",
                    }
                self.audit_results.append(audit)
                new_records.extend(records)
                new_issues.extend(issues)
                new_info.append({
                    "file": Path(path).name,
                    "bank": bank,
                    "pages": pages,
                    "records": len(records),
                    "issues": len(issues)
                })
            except Exception as exc:
                new_issues.append({
                    "source": Path(path).name,
                    "page": "-",
                    "date_text": "",
                    "reason": f"Falha ao ler PDF: {exc}",
                    "description": "",
                    "value_text": ""
                })

        self.records.extend(new_records)
        self.issues.extend(new_issues)
        self.files_info.extend(new_info)
        self.refresh_table()

        banks = sorted(set(info["bank"] for info in self.files_info))
        self.bank_var.set("Bancos identificados: " + (", ".join(banks) if banks else "—"))
        self.count_var.set(f"Lançamentos: {len(self.records)}")
        self.issue_var.set(f"Pendências: {len(self.issues)}")

        total_pages = sum(info["pages"] for info in new_info)
        self.status_var.set(
            f"Leitura concluída: {len(paths)} arquivo(s), {total_pages} página(s), "
            f"{len(new_records)} lançamento(s) novo(s), {len(new_issues)} pendência(s)."
        )

        if new_issues:
            messagebox.showwarning(
                "Conferência necessária",
                f"Foram identificadas {len(new_issues)} pendência(s).\n"
                "Os itens não reconhecidos não foram descartados silenciosamente. "
                "Consulte a lista de pendências antes de considerar a importação concluída."
            )

    def show_issues(self):
        if not self.issues:
            messagebox.showinfo("Pendências", "Nenhuma pendência de leitura foi registrada.")
            return
        win = tk.Toplevel(self.root)
        win.title("Pendências de leitura")
        win.geometry("1050x420")
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        cols = ("source", "page", "date", "reason", "description", "value")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        labels = {"source":"ARQUIVO", "page":"PÁG.", "date":"DATA", "reason":"MOTIVO", "description":"DESCRIÇÃO", "value":"VALOR LIDO"}
        widths = {"source":180, "page":55, "date":90, "reason":360, "description":250, "value":100}
        for col in cols:
            tree.heading(col, text=labels[col])
            tree.column(col, width=widths[col], anchor="w")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for issue in self.issues:
            tree.insert("", "end", values=(issue.get("source", ""), issue.get("page", ""), issue.get("date_text", ""), issue.get("reason", ""), issue.get("description", ""), issue.get("value_text", "")))

    def show_audit(self):
        if not self.audit_results:
            messagebox.showinfo("Conferência OCR", "Ainda não há relatórios. Adicione os PDFs novamente para executar a segunda leitura OCR.")
            return
        win = tk.Toplevel(self.root)
        win.title("Conferência independente por OCR e saldos")
        win.geometry("1120x560")
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        cols = ("source", "page", "records", "tokens", "status", "detail")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        labels = {"source":"ARQUIVO", "page":"PÁG.", "records":"LANÇAMENTOS", "tokens":"VALORES OCR", "status":"RESULTADO", "detail":"OBSERVAÇÃO"}
        widths = {"source":210, "page":55, "records":90, "tokens":90, "status":300, "detail":340}
        for col in cols:
            tree.heading(col, text=labels[col])
            tree.column(col, width=widths[col], anchor="w")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for audit in self.audit_results:
            if audit.get("error"):
                tree.insert("", "end", values=(audit["source"], "-", "-", "-", "OCR indisponível", audit["error"]))
            for page in audit.get("pages", []):
                tree.insert("", "end", values=(audit["source"], page["page"], page["records"], page["ocr_money_tokens"], page["status"], page.get("detail", "")))
            bal = audit.get("balance", {})
            tree.insert("", "end", values=(audit["source"], "—", "—", "—", bal.get("status", "Saldo não validado"), bal.get("detail", "")))
        ttk.Label(win, text="A segunda leitura procura valores em linhas com contexto de movimentação nos layouts Asaas, Cora e Mercado Pago. Nos demais bancos, a leitura OCR complementar é apenas indicativa. Divergências exigem conferência visual; nenhum valor é corrigido automaticamente.", wraplength=1080, foreground="#555").pack(anchor="w", padx=12, pady=(0, 10))

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for rec in self.records:
            value_text = f"{rec['value']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            review_text = "REVISAR" if rec.get("review") else "OK"
            tag = ("review",) if rec.get("review") else ()
            self.tree.insert(
                "",
                "end",
                values=(
                    rec["date"].strftime("%d/%m/%Y"),
                    value_text,
                    rec["description"],
                    rec["source"],
                    rec["page"],
                    review_text
                ),
                tags=tag
            )

    def clear(self):
        if self.records or self.issues:
            if not messagebox.askyesno("Limpar", "Deseja remover os arquivos e lançamentos carregados?"):
                return
        self.records.clear()
        self.issues.clear()
        self.files_info.clear()
        self.audit_results.clear()
        self.refresh_table()
        self.bank_var.set("Bancos identificados: —")
        self.count_var.set("Lançamentos: 0")
        self.issue_var.set("Pendências: 0")
        self.status_var.set("Selecione um ou mais extratos PDF para começar.")

    def export(self):
        if Workbook is None:
            messagebox.showerror(
                "Dependência ausente",
                "openpyxl não está instalado.\n\nExecute:\npip install -r requirements.txt"
            )
            return
        if not self.records:
            messagebox.showinfo("Sem lançamentos", "Nenhum lançamento disponível para exportação.")
            return
        review_count = sum(1 for rec in self.records if rec.get("review"))
        if self.issues or review_count:
            proceed = messagebox.askyesno(
                "Conferência necessária",
                f"Há {len(self.issues)} pendência(s) de leitura e {review_count} lançamento(s) extraído(s) por OCR que exigem conferência visual.\n"
                "Somente os lançamentos reconhecidos serão exportados.\n\n"
                "Você conferiu os itens marcados como REVISAR e deseja continuar?"
            )
            if not proceed:
                return

        output = filedialog.asksaveasfilename(
            title="Salvar planilha para o Domínio",
            defaultextension=".xlsx",
            initialfile="Importacao_Dominio.xlsx",
            filetypes=[("Excel", "*.xlsx")]
        )
        if not output:
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Importação Domínio"

        headers = ["DATA", "DEBITO", "CREDITO", "VALOR", "", "HISTORICO"]
        for col, header in enumerate(headers, start=1):
            ws.cell(row=1, column=col, value=header)

        for row_number, rec in enumerate(self.records, start=2):
            ws.cell(row=row_number, column=1, value=rec["date"])
            ws.cell(row=row_number, column=1).number_format = "DD/MM/YYYY"
            ws.cell(row=row_number, column=4, value=rec["value"])
            ws.cell(row=row_number, column=4).number_format = '#,##0.00;[Red]-#,##0.00'
            ws.cell(row=row_number, column=6, value=rec["description"])

        # Larguras úteis, sem negrito, cores ou decoração.
        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["D"].width = 16
        ws.column_dimensions["F"].width = 70

        try:
            wb.save(output)
        except Exception as exc:
            messagebox.showerror("Erro ao salvar", f"Não foi possível salvar a planilha:\n{exc}")
            return

        messagebox.showinfo(
            "Exportação concluída",
            f"Planilha salva com sucesso!\n\n"
            f"Lançamentos exportados: {len(self.records)}\n"
            f"Pendências de leitura: {len(self.issues)}\n\n"
            f"Arquivo:\n{output}"
        )


def main():
    if tk is None:
        raise RuntimeError(
            "A interface gráfica exige Tkinter. A função parse_pdf pode ser "
            "usada pela auditoria sem Tkinter."
        )
    root = tk.Tk()
    ImporterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
