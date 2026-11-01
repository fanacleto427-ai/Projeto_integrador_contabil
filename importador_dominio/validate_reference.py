"""Avaliação externa: o gabarito nunca é passado ao leitor de produção."""
import argparse
import hashlib
import json
import unicodedata
from decimal import Decimal
from pathlib import Path


def norm(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text.upper())
                            if not unicodedata.combining(c)).split())


def compare(result, case):
    reference = {(r["page"], r["source_row_on_page"]): r for r in case["expected_transactions"]}
    assert len(reference) == len(case["expected_transactions"])
    seen = set()
    rows = []
    extras = []
    for r in result["records"]:
        key = tuple(map(int, r["occurrence_id"].split(":")[-2:]))
        if key in seen or key not in reference:
            extras.append(r)
            continue
        seen.add(key)
        e = reference[key]
        fields = []
        if r["date"] != e["date"]:
            fields.append("date")
        if Decimal(str(r["value"])) != Decimal(e["value"]):
            fields.append("value")
        if norm(r["description"]) != norm(e["description"]):
            fields.append("description")
        rows.append(dict(page=key[0], row=key[1], expected=e, candidate=r, incorrect_fields=fields))
    missing = [r for key,r in reference.items() if key not in seen]
    return dict(
        scope="Santander; comparação da candidata com referência independente por IA, não certificação humana",
        expected=len(reference), candidate_records=len(result["records"]),
        detected_occurrences=len(result["occurrences"]),
        exact=sum(not r["incorrect_fields"] for r in rows),
        exact_money=sum("value" not in r["incorrect_fields"] for r in rows),
        date_errors=sum("date" in r["incorrect_fields"] for r in rows),
        value_errors=sum("value" in r["incorrect_fields"] for r in rows),
        description_errors=sum("description" in r["incorrect_fields"] for r in rows),
        missing=missing, extras=extras, rows=rows, issues=result["issues"],
        approved=False, status="CANDIDATA PARCIAL — REVISAR",
        uncompleted=["Correções dos leitores Asaas/Cora/Mercado Pago",
                     "Correção/validação das descrições OCR remanescentes",
                     "Resolução documental dos valores divergentes",
                     "Regressão completa dos demais leitores",
                     "Validação visual da interface Tkinter em ambiente com display"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    g = json.loads(args.gold.read_text())
    case = next(c for c in g["cases"] if c["bank"] == "Santander")
    report = compare(json.loads(args.result.read_text()), case)
    report["reference_code_sha256"] = hashlib.sha256(
        (Path(__file__).parent/"reference/importador_v1_12.py").read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("rows","issues","uncompleted")}, ensure_ascii=False))
