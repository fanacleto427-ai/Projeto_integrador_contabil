"""Regressão externa por página e ocorrência. Não passa o gabarito aos leitores."""
import argparse
import hashlib
import json
import unicodedata
from decimal import Decimal
from pathlib import Path

from app import load
from native_readers import parse_cora, parse_mercado_pago


def canonical(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD",text.upper())
                            if not unicodedata.combining(c)).split())


def compare(records, traces, expected):
    ref={(r["page"],r["source_row_on_page"]):r for r in expected}
    if len(ref)!=len(expected):
        raise ValueError("Referência com posições físicas repetidas; requer conferência")
    seen=set()
    results=[]
    for trace in traces:
        position=tuple(map(int,trace["occurrence_id"].split(":")[-2:]))
        if position in seen:raise ValueError("Ocorrência duplicada na trilha")
        seen.add(position)
        e=ref.get(position)
        if not e:
            results.append(dict(position=position,status="extra",candidate=trace))
            continue
        wrong=[]
        if not trace.get("date_text"):
            wrong.append("date")
        else:
            from datetime import datetime
            try: actual_date=datetime.strptime(trace["date_text"],"%d/%m/%Y").date().isoformat()
            except ValueError:actual_date=None
            if actual_date!=e["date"]:wrong.append("date")
        if trace.get("value") is None or Decimal(trace["value"])!=Decimal(e["value"]):wrong.append("value")
        if canonical(trace["description"])!=canonical(e["description"]):wrong.append("description")
        for field in ("counterparty","counterparty_taxpayer_id"):
            if field in e and canonical(str(trace.get(field) or ""))!=canonical(str(e.get(field) or "")):
                wrong.append(field)
        results.append(dict(position=position,status="divergent" if wrong else "exact",
                            incorrect_fields=wrong,expected=e,candidate=trace))
    missing=[r for key,r in ref.items() if key not in seen]
    return dict(expected=len(expected),records=len(records),occurrences=len(traces),
                exact=sum(r["status"]=="exact" for r in results),
                unresolved=sum(r["status"]=="divergent" for r in results),
                extras=sum(r["status"]=="extra" for r in results),missing=missing,
                details=results,approved=False)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--assets",type=Path,default=Path(".local/conversation-workspace/files/attached_assets"))
    parser.add_argument("--output",type=Path,default=Path("generated-artifacts"))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    gold=json.loads((args.assets/"gabaritos_referencia_22_pdfs_revisado_4_bancos.json").read_text())
    base=load()
    reports=[]
    for bank,pattern,reader,name in (
        ("Mercado Pago","EXTRATO_BANCARIO_Mercado*.pdf",parse_mercado_pago,"mercado-pago"),
        ("Cora","EXTRATO_BANCARIO_CORA*.pdf",parse_cora,"cora")):
        pdf=next(args.assets.glob(pattern))
        records,issues,traces=reader(pdf,base)
        expected=next(c for c in gold["cases"] if c["bank"]==bank)["expected_transactions"]
        report=compare(records,traces,expected)
        report.update(bank=bank,issues=issues,pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
        reports.append(report)
        (args.output/f"{name}-candidata.json").write_text(json.dumps(
            dict(bank=bank,records=records,issues=issues,occurrences=traces,approved=False),
            ensure_ascii=False,indent=2,default=str),encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k not in ("details","issues","pdf_sha256")},
                         ensure_ascii=False),flush=True)
    (args.output/"cora-mercado-validacao.json").write_text(
        json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
