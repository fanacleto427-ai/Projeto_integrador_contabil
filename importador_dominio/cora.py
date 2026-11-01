"""Cora: texto das operações + leitura visual das datas ausentes no texto."""
import re
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from document_rows import Audit, words, lines, line_text, money, date_image


def parse(pdf_path, base, date_reader=None):
    audit = Audit(pdf_path, base)
    date_reader = date_reader or date_image
    current_date = None
    date_origin = None
    with pymupdf.open(pdf_path) as doc, ThreadPoolExecutor(max_workers=4) as pool:
        for pn,page in enumerate(doc,1):
            # This supported layout has a stable, point-based column grid.
            if abs(page.rect.width-752) > 5:
                audit.issue(pn, "Layout Cora não suportado: largura inesperada")
                current_date = None
                continue
            rows = lines(words(page))
            events, futures = [], {}
            for row in rows:
                y, rw = row["cy"], row["words"]
                if not 130 < y < 990:
                    continue
                full = line_text(rw)
                if full.startswith(("Total de entradas", "Total de saídas", "Saldo inicial", "Saldo final")):
                    continue
                if "Saldo do dia" in full:
                    box = (30,y-14,165,y+14)
                    # Render on this thread: PyMuPDF document objects aren't thread-safe.
                    if date_reader is date_image:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(4,4), clip=pymupdf.Rect(box), alpha=False)
                        from PIL import Image
                        import pytesseract
                        image = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                        futures[y] = pool.submit(pytesseract.image_to_string,image,lang="por",
                                                 config="--psm 7",timeout=30)
                    else:
                        futures[y] = pool.submit(date_reader,page,box)
                    events.append(("date",row))
                elif any(60 <= w["x"] < 250 for w in rw):
                    # Every row in the category column is retained, not a keyword whitelist.
                    events.append(("transaction",row))
            if not events:
                audit.issue(pn, "Tabela Cora ausente ou sem camada textual utilizável")
                current_date = None
            for kind,row in events:
                y,rw = row["cy"],row["words"]
                if kind == "date":
                    try:
                        raw = futures[y].result().strip()
                    except Exception as exc:
                        raw = ""
                        audit.issue(pn, f"Falha na leitura da data: {exc}")
                    dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b",raw)
                    current_date = dates[0] if len(dates)==1 else None
                    date_origin = dict(page=pn,cy=y,raw=raw)
                    if not current_date:
                        audit.issue(pn, f"Data de grupo Cora ilegível em y={y:.2f}")
                    continue
                category = line_text([w for w in rw if 60<=w["x"]<250])
                party = line_text([w for w in rw if 250<=w["x"]<425])
                taxid = line_text([w for w in rw if 425<=w["x"]<570])
                raw = line_text([w for w in rw if w["x"]>=590])
                description = " ".join(v for v in (category,party,taxid) if v)
                audit.add(pn,current_date,money(raw,signed=True),description,
                          dict(source_y=y, primary_tokens=[raw], date_origin=date_origin,
                               date_from_page_continuation=bool(date_origin and date_origin["page"]!=pn),
                               crop_bbox=[60,y-14,720,y+14]),
                          transaction_type=category,counterparty=party,counterparty_taxpayer_id=taxid)
    return audit.result()
