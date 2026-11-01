"""Mercado Pago: grupos delimitados por linhas visuais, valor separado de saldo."""
import re

import pymupdf
from PIL import Image

from document_rows import Audit, words, lines, line_text, money, norm


def separators(page, top, bottom):
    """Find horizontal rules in the rendered page, not balance values."""
    pix = page.get_pixmap(colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L",(pix.width,pix.height),pix.samples)
    found = []
    for y in range(int(top), int(bottom)):
        # Background is off-white (~250); separators are gray across the table.
        values = [image.getpixel((x,y)) for x in range(55,695,4)]
        if sum(v<245 for v in values) >= len(values)*.9 and max(values)-min(values)<35:
            if not found or y-found[-1][-1]>2:
                found.append([])
            found[-1].append(y)
    return [sum(g)/len(g) for g in found]


def direction(description):
    d = norm(description)
    if d.startswith(("COMPRA NO DEBITO","PAGAMENTO DA FATURA","TRANSFERENCIA ENVIADA PELO PIX")):
        return -1
    if d.startswith(("DEPOSITO RECEBIDO POR BOLETO","TRANSFERENCIA RECEBIDA PELO PIX")):
        return 1
    return None


def parse(pdf_path, base, separator_reader=None):
    audit = Audit(pdf_path,base)
    previous_date = None
    separator_reader = separator_reader or separators
    with pymupdf.open(pdf_path) as doc:
        for pn,page in enumerate(doc,1):
            if abs(page.rect.width-752)>5:
                audit.issue(pn,"Layout Mercado Pago não suportado: largura inesperada")
                previous_date = None
                continue
            ws = words(page)
            headers = [w for w in ws if w["text"]=="Descrição" and 150<w["x"]<300]
            if len(headers)!=1:
                audit.issue(pn,"Cabeçalho da tabela Mercado Pago não identificado")
                previous_date = None
                continue
            top = headers[0]["bottom"]+5
            footer = [w["y"] for w in ws if w["text"]=="Data" and w["y"]>900]
            bottom = min(footer) if footer else 940
            rules = separator_reader(page,top,bottom)
            bounds = [top]+[y for y in rules if top+3<y<bottom]+[bottom]
            table = [w for w in ws if top<w["cy"]<bottom]
            for gi,(start,end) in enumerate(zip(bounds,bounds[1:])):
                group = [w for w in table if start<w["cy"]<end]
                dates = [w["text"].replace("-","/") for w in group
                         if w["x"]<160 and re.fullmatch(r"\d{2}-\d{2}-\d{4}",w["text"])]
                continued = not dates and gi==0 and pn>1
                date = dates[0] if len(dates)==1 else previous_date if continued else None
                # No date inheritance for a later group without its own anchor.
                descrows = lines([w for w in group if 165<=w["x"]<520])
                valuewords = [w for w in group if 520<=w["x"]<610]
                starts = [r for r in descrows if direction(line_text(r["words"])) is not None]
                # Unknown categories with money are still candidates, with unresolved sign.
                for r in descrows:
                    if r not in starts and any(abs(v["cy"]-r["cy"])<9 for v in valuewords):
                        starts.append(r)
                starts.sort(key=lambda r:r["cy"])
                used_values = set()
                for i,row in enumerate(starts):
                    y = row["cy"]
                    next_y = starts[i+1]["cy"]-8 if i+1<len(starts) else end
                    desc = " ".join(line_text(r["words"]) for r in descrows if y-6<=r["cy"]<next_y)
                    vals = [w for w in valuewords if abs(w["cy"]-y)<9]
                    used_values.update(id(w) for w in vals)
                    raw = line_text(vals)
                    value = money(raw)
                    sign = direction(desc)
                    reasons = []
                    displaced = []
                    # A continuation can print an unsigned amount on the far right.
                    # This is an explicit hypothesis, NEVER a fallback to a signed balance.
                    if not vals and continued and len(starts)==1:
                        displaced = [w for w in group if 610<=w["x"]<710 and abs(w["cy"]-y)<9]
                        candidate = line_text(displaced)
                        if re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}", candidate):
                            value = money(candidate)
                            reasons.append("Valor deslocado fora da coluna Valor: hipótese não confirmada; conferir no PDF, não tratar como saldo")
                    if sign is None:
                        reasons.append("Sentido da operação não reconhecido; não inferir pelo saldo")
                        value = None
                    elif value is not None:
                        if value<0 and sign>0:
                            reasons.append("Sinal explícito diverge do tipo da operação")
                        else:
                            value = abs(value)*sign
                    audit.add(pn,date,value,desc,
                              dict(source_y=y,primary_tokens=[raw],group_bbox=[45,start,710,end],
                                   displaced_tokens=[line_text(displaced)] if displaced else [],
                                   date_from_page_continuation=continued,
                                   crop_bbox=[165,y-10,610,next_y]), reasons)
                orphan = [w for w in valuewords if id(w) not in used_values]
                if orphan:
                    audit.issue(pn,"Valor sem histórico associado na coluna Valor: "+line_text(orphan))
                if group and not starts and descrows:
                    audit.issue(pn,"Texto de operação sem âncora reconhecida: "+
                                " ".join(line_text(r["words"]) for r in descrows))
                if dates:
                    previous_date = date
                elif starts and not continued:
                    previous_date = None
    return audit.result()
