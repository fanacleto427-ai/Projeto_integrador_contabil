"""Auditoria local sem interface gráfica. Não exporta importação aprovada."""
import argparse
import json
from pathlib import Path

from app import load
from santander import parse


def main():
    args = argparse.ArgumentParser()
    args.add_argument("pdf", type=Path)
    args.add_argument("--output", type=Path, required=True)
    args.add_argument("--bank", choices=["Santander","Asaas","Cora","Mercado Pago"], default="Santander")
    options = args.parse_args()
    base = load()
    reader=parse
    if options.bank=="Asaas":
        from asaas import parse as reader
    elif options.bank=="Cora":
        from cora import parse as reader
    elif options.bank=="Mercado Pago":
        from mercado_pago import parse as reader
    records, issues, occurrences = reader(options.pdf, base)
    result = dict(status="REVISAR", records=records, issues=issues,
                  occurrences=occurrences, version="candidata-seguranca-1",
                  approved=False,bank=options.bank)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
    print(json.dumps(dict(records=len(records), occurrences=len(occurrences), issues=len(issues),
                          approved=False)))


if __name__ == "__main__":
    main()
