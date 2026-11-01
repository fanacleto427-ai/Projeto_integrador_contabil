"""Faixas delimitadas por datas: histórico multilinha e valor sem correção por saldo."""
import hashlib
import re
from pathlib import Path
from statistics import median

import pymupdf as fitz
import pytesseract
from PIL import Image

from santander import amount, local_read


def parse(pdf_path, base, word_reader=None):
    word_reader = word_reader or (lambda page, pn: base._ocr_page_with_psm(page, scale=3, psm=11))
    records, issues, traces = [], [], []
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    with fitz.open(pdf_path) as doc:
        for pn, page in enumerate(doc, 1):
            try:
                words = word_reader(page, pn)
            except Exception as exc:
                issues.append(base._issue(pdf_path, pn, "", f"Falha OCR Asaas: {exc}"))
                continue
            anchors = sorted([w for w in words if w["x"]<450 and re.fullmatch(r"\d{2}/\d{2}/\d{4}",w["text"])], key=lambda w:w["cy"])
            if not anchors:
                issues.append(base._issue(pdf_path,pn,"","Página sem âncoras de data; conferir conteúdo"))
                continue
            half = median([b["cy"]-a["cy"] for a,b in zip(anchors,anchors[1:])])/2 if len(anchors)>1 else 55
            for i, anchor in enumerate(anchors):
                top = (anchors[i-1]["cy"]+anchor["cy"])/2 if i else anchor["cy"]-half
                bottom = (anchor["cy"]+anchors[i+1]["cy"])/2 if i+1<len(anchors) else anchor["cy"]+half
                band = [w for w in words if top<=w["cy"]<bottom]
                lines=[]
                for w in sorted([w for w in band if 450<=w["x"]<1850],key=lambda w:w["cy"]):
                    if not lines or abs(w["cy"]-lines[-1][0]["cy"])>12:
                        lines.append([w])
                    else:lines[-1].append(w)
                desc=" ".join(w["text"] for line in lines for w in sorted(line,key=lambda w:w["x"]))
                primary=[w["text"].replace("R$","").strip() for w in sorted(band,key=lambda w:w["x"])
                         if w["x"]>=1850 and w["text"].replace("R$","").strip()]
                currency=[w for w in band if w["x"]>=1850 and w["text"]=="R$"]
                left=(currency[0]["x"]+currency[0]["w"])/3 if len(currency)==1 else 620
                rect=fitz.Rect(left,anchor["cy"]/3-17,page.rect.width-15,anchor["cy"]/3+17)
                pix=page.get_pixmap(matrix=fitz.Matrix(4,4),clip=rect,alpha=False)
                reasons=[]
                try:
                    raw=local_read(Image.frombytes("RGB",(pix.width,pix.height),pix.samples))
                    secondary=[t.replace("R$","").strip() for t in raw if t.replace("R$","").strip()]
                except Exception as exc:
                    secondary=[]
                    reasons.append(f"Falha releitura: {exc}")
                a,b=amount(primary),amount(secondary)
                if a is None or b is None or a!=b:
                    reasons.append("Valor Asaas divergente/inválido: conferência documental necessária")
                value=a if a is not None else b
                constrained=[]
                if value is None:
                    # Hipótese adicional, não confirmação: guardar também as leituras inválidas.
                    try:
                        hypothesis=pytesseract.image_to_string(
                            Image.frombytes("RGB",(pix.width,pix.height),pix.samples),lang="por",
                            config="--psm 6 -c tessedit_char_whitelist=0123456789.,-+",timeout=30)
                        constrained=hypothesis.split()
                        value=amount(constrained)
                        reasons.append("Hipótese de OCR com alfabeto monetário restrito; não confirmada pelas leituras livres")
                    except Exception as exc:
                        reasons.append(f"Falha na hipótese monetária restrita: {exc}")
                oid=f"{digest}:{pn}:{i+1}"
                trace=dict(occurrence_id=oid,page=pn,date_text=anchor["text"],description=desc,
                           primary_tokens=primary,secondary_tokens=secondary,constrained_tokens=constrained,reasons=reasons,
                           crop_bbox=list(rect),status="REVISAR")
                traces.append(trace)
                if value is not None and desc:
                    try:
                        rec=base._new_record(anchor["text"],value,desc,pdf_path,pn)
                        rec.update(occurrence_id=oid,source_path=str(Path(pdf_path).resolve()),evidence=trace,
                                   review=True,note="Asaas: histórico reconstruído por linhas; conferir todos os campos.")
                        records.append(rec)
                    except ValueError as exc:reasons.append(str(exc))
                else:reasons.append("Ocorrência sem valor/histórico utilizável; não descartada da auditoria")
                for reason in reasons:
                    issues.append(dict(base._issue(pdf_path,pn,anchor["text"],reason,desc," | ".join(primary+secondary)),occurrence_id=oid))
    return records,issues,traces
