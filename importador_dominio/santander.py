"""Leitor candidato: preservação estrutural e conflitos explícitos, sem gabarito."""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pymupdf as fitz
import pytesseract
from PIL import Image

MONEY = re.compile(r"-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}")
DATE = re.compile(r"\d{2}/\d{2}/\d{4}")


def amount(tokens):
    """Não aceitar apenas o sufixo válido de um valor fragmentado."""
    if len(tokens) != 1 or not MONEY.fullmatch(tokens[0]):
        return None
    return Decimal(tokens[0].replace(".", "").replace(",", "."))


def local_read(image):
    data = pytesseract.image_to_data(
        image, lang="por", config="--psm 6",
        output_type=pytesseract.Output.DICT, timeout=30)
    # Não descartar fragmentos monetários por confiança.
    return [str(t).strip() for t in data["text"] if str(t).strip()]


def parse(pdf_path, base, row_reader=None, cell_reader=None):
    row_reader = row_reader or (lambda page, pn: base._ocr_visual_rows(page, 2, 16))
    cell_reader = cell_reader or local_read
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    records, issues, occurrences = [], [], []
    active = False
    found_table = False
    with fitz.open(pdf_path) as doc, ThreadPoolExecutor(max_workers=4) as pool:
        for pn, page in enumerate(doc, 1):
            try:
                rows = row_reader(page, pn)
            except Exception as exc:
                issues.append(base._issue(pdf_path, pn, "", f"Falha OCR: {exc}"))
                continue
            pending = []
            for row in rows:
                words = sorted(row["words"], key=lambda w: w["x"])
                dates = [w for w in words if w["x"] < 250 and DATE.fullmatch(w["text"])]
                desc = " ".join(w["text"] for w in words if 250 <= w["x"] < 990)
                raw = [w["text"] for w in words if 1120 <= w["x"] < 1300]
                norm = base._normalize_bank_text(desc)
                if "SALDO ANTERIOR" in norm:
                    active = found_table = True
                    continue
                full = base._normalize_bank_text(" ".join(w["text"] for w in words))
                if not dates and ("SALDO DISPONIVEL" in full or
                                  ("INVESTIMENTOS" in full and "RESGATE AUTOMATICO" in full)):
                    active = False
                if not active:
                    continue
                if not dates:
                    if desc and any(MONEY.fullmatch(t) for t in raw):
                        issues.append(base._issue(pdf_path, pn, "", "Possível movimento sem data; conferir página", desc, " ".join(raw)))
                    continue
                oid = f"{digest}:{pn}:{len(pending)+1}"
                date = dates[0]["text"]
                if len(dates) != 1:
                    issues.append(dict(base._issue(pdf_path, pn, date, "Datas ambíguas", desc), occurrence_id=oid))
                # Âncora descoberta no OCR, nunca coordenadas ou conteúdo do gabarito.
                cy = dates[0]["cy"] / 2
                box = fitz.Rect(550, cy-12, 640, cy+12)
                pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=box, alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                pending.append((oid, date, desc, raw, box, pool.submit(cell_reader, image)))
            for oid, date, desc, raw, box, future in pending:
                reasons = []
                try:
                    secondary = future.result()
                except Exception as exc:
                    secondary = []
                    reasons.append(f"Falha releitura: {exc}")
                primary_value, secondary_value = amount(raw), amount(secondary)
                if primary_value is None:
                    reasons.append("Valor principal inválido; candidato complementar requer conferência")
                if secondary_value is None or primary_value != secondary_value:
                    reasons.append("Divergência entre leituras; não escolher automaticamente")
                if not desc:
                    reasons.append("Histórico vazio")
                value = primary_value if primary_value is not None else secondary_value
                trace = dict(occurrence_id=oid, page=pn, date_text=date, description=desc,
                             primary_tokens=raw, secondary_tokens=secondary,
                             primary_value=str(primary_value) if primary_value is not None else None,
                             secondary_value=str(secondary_value) if secondary_value is not None else None,
                             crop_bbox=list(box), reasons=reasons, status="REVISAR")
                occurrences.append(trace)
                if value is not None:
                    try:
                        rec = base._new_record(date, value, desc, pdf_path, pn)
                        rec.update(occurrence_id=oid, review=True, evidence=trace,
                                   source_path=str(Path(pdf_path).resolve()),
                                   note="Candidato OCR; conferir data, valor e histórico. " + "; ".join(reasons))
                        records.append(rec)
                    except ValueError as exc:
                        reasons.append(str(exc))
                else:
                    reasons.append("Nenhum valor utilizável; ocorrência mantida na auditoria")
                for reason in reasons:
                    issues.append(dict(base._issue(pdf_path, pn, date, reason, desc,
                                                   " | ".join(raw + secondary)), occurrence_id=oid))
    if not found_table:
        issues.append(base._issue(pdf_path, "-", "", "Tabela Santander não delimitada com segurança; layout não suportado."))
    return records, issues, occurrences
