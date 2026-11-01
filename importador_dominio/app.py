"""Executa a versão candidata sem editar a referência congelada."""
import hashlib
import importlib.util
import json
from pathlib import Path

from santander import parse

REFERENCE_SHA = "7b7556c4a257ef6a6b5ee7e151916a1bee7cdb5e4eb5ab984a97794c76f8a98b"


def load():
    path = Path(__file__).parent / "reference/importador_v1_12.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != REFERENCE_SHA:
        raise RuntimeError("Referência v1.12 alterada. Execução interrompida.")
    spec = importlib.util.spec_from_file_location("dominio_reference", path)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.APP_TITLE = "Importador Domínio — candidata de segurança (não homologada)"
    traces = {}

    def santander(pdf_path):
        records, issues, occurrences = parse(pdf_path, base)
        traces[str(pdf_path)] = occurrences
        return records, issues

    base.parse_santander_pdf = santander
    def asaas(pdf_path):
        from asaas import parse as parse_asaas
        records, issues, occurrences = parse_asaas(pdf_path, base)
        traces[str(pdf_path)] = occurrences
        return records, issues
    base.parse_asaas_pdf = asaas
    def cora(pdf_path):
        from cora import parse as reader
        records, issues, occurrences = reader(pdf_path, base)
        traces[str(pdf_path)] = occurrences
        return records, issues
    def mercado_pago(pdf_path):
        from mercado_pago import parse as reader
        records, issues, occurrences = reader(pdf_path, base)
        traces[str(pdf_path)] = occurrences
        return records, issues
    base.parse_cora_pdf = cora
    base.parse_mercado_pago_pdf = mercado_pago
    original_parse = base.parse_pdf

    def parse_with_review(pdf_path):
        records, issues, bank, pages = original_parse(pdf_path)
        for rec in records:
            rec["source_path"] = str(Path(pdf_path).resolve())
            rec["review"] = True  # Leitura nativa também exige conferência individual.
        return records, issues, bank, pages
    base.parse_pdf = parse_with_review
    original_app = base.ImporterApp

    class ReviewedApp(original_app):
        def __init__(self, root):
            super().__init__(root)
            root.title("Importador Domínio — candidata NÃO HOMOLOGADA")
            bar = base.ttk.Frame(root)
            bar.pack(fill="x")
            base.ttk.Label(bar, text="NÃO HOMOLOGADA — conferência documental obrigatória").pack(side="left")
            base.ttk.Button(bar, text="Conferir lançamento selecionado", command=self.review_selected).pack(side="left")
            base.ttk.Button(bar, text="Salvar trilha de auditoria", command=self.save_trace).pack(side="left")
            base.ttk.Button(bar, text="Conferir ocorrência sem registro", command=self.review_missing).pack(side="left")
            self.review_log = []
            self._batch_epoch = 0

        def refresh_table(self):
            super().refresh_table()
            self.count_var.set(f"Lançamentos: {len(self.records)}")
            self.issue_var.set(f"Pendências: {len(self.issues)}")

        def clear(self):
            # Distinguir cancelamento de confirmação, inclusive numa sessão só com trilha.
            if (self.records or self.issues or self.review_log or traces) and not base.messagebox.askyesno(
                "Limpar", "Deseja remover os arquivos, lançamentos e a trilha de conferência carregados?"
            ):
                return
            self.records.clear()
            self.issues.clear()
            self.files_info.clear()
            self.audit_results.clear()
            self.review_log.clear()
            traces.clear()
            self._batch_epoch += 1
            # Formulários antigos não podem recriar dados após limpar o lote.
            for child in self.root.winfo_children():
                if isinstance(child, base.tk.Toplevel):
                    child.destroy()
            self.refresh_table()
            self.bank_var.set("Bancos identificados: —")
            self.status_var.set("Selecione um ou mais extratos PDF para começar.")

        def review_missing(self):
            known = {r.get("occurrence_id") for r in self.records}
            pending_ids = {i.get("occurrence_id") for i in self.issues}
            pending = [(path,t) for path,items in traces.items() for t in items
                       if t["occurrence_id"] in pending_ids and t["occurrence_id"] not in known]
            if not pending:
                base.messagebox.showinfo("Conferência", "Não há ocorrências sem registro. Pendências documentais exigem correção do leitor.")
                return
            path, trace = pending[0]
            epoch = self._batch_epoch
            win = base.tk.Toplevel(self.root)
            win.title("Ocorrência sem registro — conferência documental")
            win.transient(self.root)
            win.grab_set()
            base.ttk.Label(win,text=f"{Path(path).name} — página {trace['page']}\n"+
                           "; ".join(trace["reasons"])).pack()
            def open_pdf():
                import webbrowser
                webbrowser.open(Path(path).resolve().as_uri()+f"#page={trace['page']}")
            base.ttk.Button(win,text="Abrir PDF original",command=open_pdf).pack()
            entries = []
            for label,value in (("Data DD/MM/AAAA",trace.get("date_text") or ""),
                                ("Valor com sinal — nunca copiar saldo",""),
                                ("Histórico",trace.get("description","")),
                                ("Justificativa documental obrigatória","")):
                base.ttk.Label(win,text=label).pack()
                entry=base.ttk.Entry(win,width=85)
                entry.insert(0,value)
                entry.pack()
                entries.append(entry)
            def confirm():
                from santander import amount
                try:
                    if epoch != self._batch_epoch:
                        raise ValueError("O lote foi limpo. Abra novamente a conferência.")
                    if any(r.get("occurrence_id") == trace["occurrence_id"] for r in self.records):
                        raise ValueError("Esta ocorrência já foi conferida em outra janela.")
                    if not any(i.get("occurrence_id") == trace["occurrence_id"] for i in self.issues):
                        raise ValueError("A pendência não está mais ativa neste lote.")
                    date,value,desc,reason=[e.get().strip() for e in entries]
                    parsed=amount([value])
                    if parsed is None or not desc or not reason:
                        raise ValueError("Preencha valor com sinal, histórico e justificativa.")
                    rec=base._new_record(date,parsed,desc,path,trace["page"])
                    rec.update(occurrence_id=trace["occurrence_id"],review=False,evidence=trace,
                               source_path=str(Path(path).resolve()),note="Conferido: "+reason)
                    self.records.append(rec)
                    self.issues=[i for i in self.issues if i.get("occurrence_id")!=trace["occurrence_id"]]
                    self.review_log.append(dict(before=trace,after=dict(rec),reason=reason))
                    self.refresh_table()
                    win.destroy()
                except ValueError as exc:
                    base.messagebox.showerror("Conferência não salva",str(exc))
            base.ttk.Button(win,text="Confirmo a conferência documental",command=confirm).pack()
            base.ttk.Button(win,text="Cancelar",command=win.destroy).pack()

        def review_selected(self):
            selected = self.tree.selection()
            if len(selected) != 1:
                base.messagebox.showinfo("Conferência", "Selecione exatamente um lançamento.")
                return
            rec = self.records[self.tree.index(selected[0])]
            epoch = self._batch_epoch
            win = base.tk.Toplevel(self.root)
            win.title("Conferência documental individual")
            win.transient(self.root)
            win.grab_set()
            base.ttk.Label(win, text=f"{rec['source']} — página {rec['page']}\n{rec.get('note','')}").pack()
            evidence = rec.get("evidence", {})
            if evidence:
                base.ttk.Label(win, text="Leitura principal: " + " ".join(evidence.get("primary_tokens", []))
                               + "\nReleitura complementar: " + " ".join(evidence.get("secondary_tokens", []))
                               + "\nValor deslocado NÃO confirmado: " + " ".join(evidence.get("displaced_tokens", []))
                               + "\nHipótese restrita, não confirmada: " + " ".join(evidence.get("constrained_tokens", []))).pack()
            if rec.get("source_path"):
                def open_pdf():
                    import webbrowser
                    webbrowser.open(Path(rec["source_path"]).as_uri() + f"#page={rec['page']}")
                base.ttk.Button(win, text="Abrir PDF original para conferência", command=open_pdf).pack()
            entries = []
            for title, value in (("Data DD/MM/AAAA", rec["date"].strftime("%d/%m/%Y")),
                                 ("Valor com sinal (ex.: -123,45)", f"{rec['value']:.2f}".replace(".", ",")),
                                 ("Histórico", rec["description"]), ("Justificativa / evidência no PDF", "")):
                base.ttk.Label(win, text=title).pack()
                entry = base.ttk.Entry(win, width=85)
                entry.insert(0, value)
                entry.pack()
                entries.append(entry)

            def confirm():
                from santander import amount
                try:
                    if epoch != self._batch_epoch or not any(r is rec for r in self.records):
                        raise ValueError("O lançamento não pertence mais ao lote atual.")
                    date = base.parse_date(entries[0].get())
                    value = amount([entries[1].get().strip()])
                    desc, reason = entries[2].get().strip(), entries[3].get().strip()
                    if value is None or not desc or not reason:
                        raise ValueError("Preencha valor, histórico e justificativa documental.")
                    before = dict(rec)
                    rec.update(date=date, value=float(value), description=desc, review=False,
                               note="Conferido individualmente: " + reason)
                    oid = rec.get("occurrence_id")
                    if oid:
                        self.issues = [i for i in self.issues if i.get("occurrence_id") != oid]
                    self.review_log.append(dict(before=before, after=dict(rec), reason=reason))
                    self.refresh_table()
                    win.destroy()
                except ValueError as exc:
                    base.messagebox.showerror("Conferência não salva", str(exc))
            base.ttk.Button(win, text="Confirmo que conferi com o documento", command=confirm).pack()
            base.ttk.Button(win, text="Cancelar", command=win.destroy).pack()

        def save_trace(self):
            output = base.filedialog.asksaveasfilename(defaultextension=".json", initialfile="auditoria_dominio.json")
            if output:
                Path(output).write_text(json.dumps(dict(occurrences=traces, issues=self.issues,
                                                       reviews=self.review_log), ensure_ascii=False,
                                                  indent=2, default=str), encoding="utf-8")

        def export(self):
            if self.issues or any(r.get("review") is not False for r in self.records):
                base.messagebox.showerror("Exportação bloqueada",
                    "Existem pendências ou lançamentos não conferidos. Salve a auditoria e confira cada item; não será gerada uma importação parcial como aprovada.")
                return
            if not self.records:
                base.messagebox.showinfo("Sem lançamentos", "Nenhum lançamento para exportar.")
                return
            output = base.filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="Importacao_Dominio.xlsx")
            if not output:
                return
            try:
                wb = base.Workbook()
                ws = wb.active
                ws.title = "Importação Domínio"
                ws.append(["DATA", "DEBITO", "CREDITO", "VALOR", "", "HISTORICO"])
                for rec in self.records:
                    ws.append([rec["date"], None, None, rec["value"], None, rec["description"]])
                    ws.cell(ws.max_row, 1).number_format = "DD/MM/YYYY"
                    ws.cell(ws.max_row, 4).number_format = '#,##0.00;[Red]-#,##0.00'
                    ws.cell(ws.max_row, 6).data_type = "s"  # histórico não vira fórmula Excel
                for col, width in (("A", 14), ("D", 16), ("F", 70)):
                    ws.column_dimensions[col].width = width
                Path(output).with_suffix(".auditoria.json").write_text(
                    json.dumps(dict(records=self.records, reviews=self.review_log,
                                    occurrences=traces, issues=self.issues, reference_sha256=REFERENCE_SHA),
                               ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                wb.save(output)
                base.messagebox.showinfo("Exportação concluída", "Planilha e trilha de conferência salvas.")
            except Exception as exc:
                base.messagebox.showerror("Falha na exportação", str(exc))
    base.ImporterApp = ReviewedApp
    return base


if __name__ == "__main__":
    load().main()
