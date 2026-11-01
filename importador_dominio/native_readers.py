"""Cora/Mercado Pago: valores nativos, geometria documental e incertezas explícitas."""
import hashlib
import re
from decimal import Decimal
from pathlib import Path
from bisect import bisect_right

import pymupdf as fitz
import pytesseract
from PIL import Image

NUMBER = r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"
DATE = re.compile(r"\d{2}/\d{2}/\d{4}")


def center(w):
    return (w[1]+w[3])/2


def text(words):
    return " ".join(w[4] for w in sorted(words,key=lambda w:w[0]))


def crop_date(page, y):
    readings=[]
    for scale in (4,3):
        rect=fitz.Rect(25,y-12,175,y+12)
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=rect,alpha=False)
        im=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
        try:
            readings.append(pytesseract.image_to_string(im,lang="por",config="--psm 7",timeout=30).strip())
        except Exception as exc:
            readings.append("ERRO: "+str(exc))
    valid=[r for r in readings if DATE.fullmatch(r)]
    return (valid[0] if valid else None), readings, not(len(valid)==2 and valid[0]==valid[1])


def append_occurrence(base, path, digest, pn, ordinal, date, value, desc, reasons,
                      records, issues, traces, **evidence):
    oid=f"{digest}:{pn}:{ordinal}"
    trace=dict(occurrence_id=oid,page=pn,date_text=date,description=desc,
               value=str(value) if value is not None else None,reasons=reasons,
               status="REVISAR",**evidence)
    traces.append(trace)
    if date and value is not None and desc:
        try:
            rec=base._new_record(date,value,desc,path,pn)
            rec.update(occurrence_id=oid,source_path=str(Path(path).resolve()),
                       review=True,evidence=trace,note="Conferir com o documento. "+"; ".join(reasons))
            # Metadados não são concatenados artificialmente ao histórico contábil.
            for key in ("counterparty","counterparty_taxpayer_id"):
                if key in evidence:rec[key]=evidence[key]
            records.append(rec)
        except ValueError as exc:reasons.append(str(exc))
    else:
        reasons.append("Ocorrência preservada sem registro exportável: data/valor/histórico não confirmado")
    for reason in reasons:
        issues.append(dict(base._issue(path,pn,date or "",reason,desc,
                                     evidence.get("raw_value","")),occurrence_id=oid))


def parse_cora(path, base):
    records,issues,traces=[],[],[]
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    current_date=None
    current_evidence={}
    with fitz.open(path) as doc:
        for pn,page in enumerate(doc,1):
            words=page.get_text("words")
            headers=[]
            for w in words:
                if w[4]=="Saldo" and w[0]>450:
                    line=[t for t in words if abs(center(t)-center(w))<4]
                    if "SALDO DO DIA" in base._normalize_bank_text(text(line)):
                        date,raw,uncertain=crop_date(page,center(w))
                        headers.append((center(w),date,raw,uncertain))
            headers.sort()
            anchors=sorted([w for w in words if w[4]=="R$" and w[0]>550],key=center)
            index=0
            ordinal=0
            for anchor in anchors:
                y=center(anchor)
                line=[w for w in words if abs(center(w)-y)<4]
                full=base._normalize_bank_text(text(line))
                if full.startswith(("TOTAL DE ENTRADAS","TOTAL DE SAIDAS","SALDO")):
                    continue
                desc=text([w for w in line if 50<w[0]<260])
                if not desc:
                    continue
                while index<len(headers) and headers[index][0]<y:
                    _,current_date,raw,uncertain=headers[index]
                    current_evidence=dict(date_readings=raw,date_uncertain=uncertain,
                                          date_header_page=pn,date_header_y=headers[index][0])
                    index+=1
                ordinal+=1
                raw_value="".join(w[4] for w in sorted(line,key=lambda w:w[0]) if w[0]>=550)
                match=re.fullmatch(r"([+-])R\$("+NUMBER+r")",raw_value)
                value=Decimal(match[1]+match[2].replace(".","").replace(",",".")) if match else None
                reasons=[]
                if value is None:reasons.append("Valor/sinal nativo Cora não identificado integralmente")
                if not current_date:reasons.append("Data Cora não identificada; não usar data antiga após cabeçalho inválido")
                if current_evidence.get("date_uncertain"):reasons.append("Leituras de data Cora discordantes ou incompletas")
                append_occurrence(base,path,digest,pn,ordinal,current_date,value,desc,reasons,records,issues,traces,
                    raw_value=raw_value,source_y=y,sign_source="sinal explícito no campo nativo",
                    counterparty=text([w for w in line if 260<=w[0]<436]),
                    counterparty_taxpayer_id=text([w for w in line if 436<=w[0]<550]),
                    date_from_page_continuation=current_evidence.get("date_header_page")!=pn,**current_evidence)
            # Há páginas com continuação e cabeçalhos abaixo das últimas operações.
            while index<len(headers):
                _,current_date,raw,uncertain=headers[index]
                current_evidence=dict(date_readings=raw,date_uncertain=uncertain,
                                      date_header_page=pn,date_header_y=headers[index][0])
                index+=1
            if not ordinal:
                issues.append(base._issue(path,pn,"","Nenhuma ocorrência Cora localizada; conferir página/layout"))
    return records,issues,traces


def separators(page, top, bottom, left, right):
    """Linhas horizontais longas da tabela rasterizada, não pontos médios de datas."""
    scale=2
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
    image=Image.frombytes("RGB",(pix.width,pix.height),pix.samples).convert("L")
    image=image.crop((int(left*scale),int(top*scale),int(right*scale),int(bottom*scale)))
    data=image.tobytes()
    width=image.width
    hits=[top+y/scale for y in range(image.height)
          if sum(v<245 for v in data[y*width:(y+1)*width])/width>.75]
    bands=[]
    for y in hits:
        if not bands or y-bands[-1][-1]>2:bands.append([y])
        else:bands[-1].append(y)
    return [sum(b)/len(b) for b in bands]


def direction(description, base):
    norm=base._normalize_bank_text(description)
    for prefix,sign in (("COMPRA NO DEBITO",-1),("PAGAMENTO DA FATURA",-1),
                        ("TRANSFERENCIA PIX ENVIADA",-1),("TRANSFERENCIA PIX RECEBIDA",1),
                        ("TRANSFERENCIA ENVIADA PELO PIX",-1),("TRANSFERENCIA RECEBIDA PELO PIX",1),
                        ("DEPOSITO RECEBIDO POR BOLETO",1)):
        if norm.startswith(prefix):return sign
    return None


def parse_mercado_pago(path, base):
    records,issues,traces=[],[],[]
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    current_date=None
    with fitz.open(path) as doc:
        for pn,page in enumerate(doc,1):
            words=page.get_text("words")
            headings={w[4]:w for w in words if 280<w[1]<350 and w[4] in ("Data","Descrição","Valor","Saldo")}
            if len(headings)!=4:
                issues.append(base._issue(path,pn,"","Cabeçalho Mercado Pago não reconhecido; não presumir colunas"))
                current_date=None
                continue
            top=max(w[3] for w in headings.values())+2
            footer=[w[1] for w in words if w[4]=="geração:" and w[1]>top]
            bottom=min(footer)-20 if footer else page.rect.height-150
            boundaries=separators(page,top,bottom,50,700)
            # Borda final pode não estar desenhada; as faixas continuam até o rodapé.
            bounds=[top]+[y for y in boundaries if top+2<y<bottom]+[bottom]
            date_words=[w for w in words if w[0]<150 and top<center(w)<bottom
                        and re.fullmatch(r"\d{2}-\d{2}-\d{4}",w[4])]
            val_left=headings["Valor"][0]-20
            # O saldo tem texto que começa à esquerda do título. Manter margem
            # impede que totais positivos sejam confundidos com valores individuais.
            val_right=headings["Saldo"][0]-35
            desc_left=(max((w[2] for w in date_words),default=140)+headings["Descrição"][0])/2
            amounts=sorted([w for w in words if val_left<=w[0]<val_right
                            and top<center(w)<bottom and re.fullmatch(NUMBER,w[4])],key=center)
            operations=[w for w in words if desc_left<=w[0]<330 and top<center(w)<bottom
                        and w[4] in ("Compra","Transferência","Depósito","Pagamento")]
            missing_values=[]
            for op in operations:
                if not any(abs(center(a)-center(op))<12 for a in amounts):
                    # Há documentos com descrição mas campo Valor vazio.
                    # Saldo nunca é uma alternativa para preencher esse campo.
                    synthetic=(val_left,op[1],val_left+1,op[3],"")
                    missing_values.append(synthetic)
            amounts=sorted(amounts+missing_values,key=center)
            ordinal=0
            for lo,hi in zip(bounds,bounds[1:]):
                anchors=[w for w in amounts if lo<center(w)<hi]
                if not anchors:continue
                dates=[w[4].replace("-","/") for w in date_words if lo<center(w)<hi]
                reasons=[]
                if len(dates)==1:current_date=dates[0]
                elif len(dates)>1:
                    current_date=None
                    reasons.append("Mais de uma data na faixa Mercado Pago; delimitadores inconclusivos")
                elif ordinal:
                    current_date=None
                    reasons.append("Nova faixa sem data: não reutilizar data do grupo anterior")
                elif not current_date:reasons.append("Faixa sem data e sem continuação documental")
                continuation=not dates
                for idx,anchor in enumerate(anchors):
                    ordinal+=1
                    a=(center(anchors[idx-1])+center(anchor))/2 if idx else lo
                    b=(center(anchor)+center(anchors[idx+1]))/2 if idx+1<len(anchors) else hi
                    desc_words=sorted([w for w in words if desc_left<=w[0]<val_left
                                       and a<center(w)<b],key=lambda w:(round(center(w)/4),w[0]))
                    # Reconstituir linhas, ordenando horizontalmente só dentro de cada linha.
                    lines=[]
                    for w in desc_words:
                        if not lines or abs(center(w)-center(lines[-1][0]))>5:lines.append([w])
                        else:lines[-1].append(w)
                    desc=" ".join(text(line) for line in lines)
                    sign=direction(desc,base)
                    row_reasons=list(reasons)
                    if sign is None:row_reasons.append("Natureza Mercado Pago não determina sinal; não inferir pelo saldo")
                    if not anchor[4]:row_reasons.append("Campo Valor vazio no PDF; coluna Saldo não pode substituir o valor individual")
                    value=Decimal(anchor[4].replace(".","").replace(",","."))*sign if sign is not None and anchor[4] else None
                    append_occurrence(base,path,digest,pn,ordinal,current_date,value,desc,row_reasons,records,issues,traces,
                        raw_value=anchor[4],source_y=center(anchor),table_band=[lo,hi],
                        value_bbox=[val_left,a,val_right,b],balance_column_excluded=True,
                        date_from_page_continuation=continuation,
                        sign_source="natureza explícita da operação; valor individual não imprime sinal")
            if not ordinal:issues.append(base._issue(path,pn,"","Nenhuma ocorrência Mercado Pago localizada"))
    return records,issues,traces
