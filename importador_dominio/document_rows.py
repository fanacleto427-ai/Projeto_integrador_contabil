"""Geometria documental compartilhada; sem consulta a saldos ou oráculos."""
import hashlib
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image


def text(words):
    return " ".join(w["text"] for w in sorted(words, key=lambda w: (round(w["cy"]/5), w["x"])))


def words(page):
    return [dict(x=x0, y=y0, right=x1, bottom=y1, cy=(y0+y1)/2, text=t)
            for x0,y0,x1,y1,t,*_ in page.get_text("words") if t.strip()]


def lines(items, tolerance=6):
    result = []
    for w in sorted(items, key=lambda w: (w["cy"], w["x"])):
        if not result or abs(w["cy"]-result[-1]["cy"]) > tolerance:
            result.append(dict(cy=w["cy"], words=[]))
        result[-1]["words"].append(w)
    return result


def line_text(items):
    return " ".join(w["text"] for w in sorted(items, key=lambda w:w["x"]))


def money(raw, signed=False):
    raw = raw.replace("R$", "").replace(" ", "").replace("−", "-")
    pattern = r"[+-]" if signed else r"[+-]?"
    if not re.fullmatch(pattern + r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}", raw):
        return None
    return Decimal(raw.replace(".", "").replace(",", "."))


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper())
                   if not unicodedata.combining(c))


def date_image(page, box):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(4,4), clip=pymupdf.Rect(box), alpha=False)
    image = Image.frombytes("RGB", (pix.width,pix.height), pix.samples)
    return pytesseract.image_to_string(image, lang="por", config="--psm 7", timeout=30).strip()


class Audit:
    def __init__(self, path, base):
        self.path, self.base = path, base
        self.digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.records, self.issues, self.occurrences = [], [], []
        self.counts = {}

    def issue(self, page, reason):
        self.issues.append(self.base._issue(self.path, page, "", reason))

    def add(self, page, date, value, description, evidence, reasons=(), **fields):
        self.counts[page] = self.counts.get(page,0)+1
        oid = f"{self.digest}:{page}:{self.counts[page]}"
        reasons = list(reasons)
        if not date:
            reasons.append("Data ausente ou ambígua; ocorrência preservada")
        if value is None:
            reasons.append("Valor/sinal ausente ou ambíguo; ocorrência preservada")
        if not description:
            reasons.append("Histórico ausente")
        trace = dict(occurrence_id=oid, page=page, date_text=date,
                     value=str(value) if value is not None else None,
                     description=description, reasons=reasons, status="REVISAR", **evidence)
        self.occurrences.append(trace)
        if date and value is not None and description:
            try:
                rec = self.base._new_record(date, value, description, self.path, page)
                rec.update(occurrence_id=oid, review=True, evidence=trace,
                           source_path=str(Path(self.path).resolve()),
                           note="Conferir individualmente com o PDF. " + "; ".join(reasons), **fields)
                self.records.append(rec)
            except ValueError as exc:
                reasons.append(str(exc))
        for reason in reasons:
            self.issues.append(dict(self.base._issue(self.path,page,date or "",reason,description),
                                    occurrence_id=oid))

    def result(self):
        if not self.occurrences:
            self.issue("-", "Nenhuma ocorrência identificada; documento não homologado")
        return self.records, self.issues, self.occurrences
