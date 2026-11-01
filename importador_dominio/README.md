# Importador Domínio — candidata de segurança

**Não homologada. Não é uma entrega 100% corrigida.**

O aplicativo original continua em `reference/importador_v1_12.py`, verificado por
SHA-256 na inicialização. As mudanças estão em módulos separados.

## Executar

Requer Python 3.11 ou superior, Tkinter para a interface, Tesseract com idioma
português e as dependências em `requirements.txt`.

No Windows, o executável usual do Tesseract é detectado pelo original. Também é
possível configurar `TESSERACT_CMD`. Não forneça credenciais.

```sh
python app.py
```

## Executável para Windows

O kit de geração fica em `windows/`. Num computador Windows, execute
`GERAR_EXE_WINDOWS.bat`; detalhes e pré-requisitos em
`windows/LEIA-ME_WINDOWS.md`. Ele usa PyInstaller, preserva e verifica a v1.12
e gera uma distribuição com `.exe` e pasta `_internal`.
O código do gerador não equivale a um executável já compilado ou homologado.
Para uso pelos fontes, Tesseract com português é uma instalação separada.
O gerador Windows pode incluir um runtime revisado, sem configuração no
computador do usuário final; ainda exige preparação de origem/licenças e
prova em Windows limpo. Veja `windows/OCR_REDISTRIBUICAO.md`.

No ambiente de desenvolvimento, da raiz do projeto:

```sh
uv run python importador_dominio/app.py
uv run python -m unittest discover -s importador_dominio/tests -v
```

Auditoria Santander sem interface:

```sh
python cli.py extrato.pdf --output resultado.json
```

Para Asaas, acrescente `--bank Asaas`.
Para Cora, use `--bank Cora`; para Mercado Pago, `--bank "Mercado Pago"`.
Os leitores alternativos de `native_readers.py` foram preservados para comparação.
Sua regressão separada (não a dos leitores ativos da interface/CLI) é:
`python validate_cora_mp.py --assets CAMINHO_DOS_PDFS_E_GABARITO --output PASTA_RESULTADOS`.

## Mudanças implementadas

- Santander: não descarta categorias como TRANSF, APLICACAO, PGTO e RECARGA.
- Preserva números dos históricos e ocorrências repetidas.
- Localiza linhas pelo próprio OCR e pelos limites da tabela, sem gabarito.
- Compara o campo monetário inteiro com uma releitura localizada 4×.
- Não aceita fragmento `500,00` isoladamente de um prefixo `-1.`.
- Mantém o valor principal quando as leituras divergem. Quando o principal é
  inválido, o complementar é apenas candidato explícito para revisão.
- Mantém a ocorrência na auditoria mesmo quando nenhum valor é utilizável.
- A interface permite conferir individualmente data, valor e histórico, exigindo
  justificativa documental. Não existe aprovação automática por concordância OCR.
- Asaas: segmentação por âncoras de data, ordenação das linhas do histórico,
  exclusão geométrica de rodapé e releitura monetária localizada. Hipóteses com
  alfabeto monetário restrito ficam identificadas e bloqueadas para conferência;
  não são confirmação do texto visual.
- Exportação Domínio bloqueada enquanto houver pendências ou linhas não conferidas.
- A exportação escreve um JSON de auditoria ao lado do XLSX. Históricos são texto,
  nunca fórmulas Excel.

## Limites importantes

- O Santander permanece com ambiguidades OCR e históricos a conferir.
- Cora e Mercado Pago usam módulos separados, não os leitores congelados.
  Cora lê datas pela imagem e preserva grupos entre páginas; o histórico inclui
  categoria, contraparte e CPF/CNPJ disponíveis no documento, sem completar
  nomes que o próprio banco truncou. Mercado Pago usa divisórias visuais para
  associar datas e continua grupos entre páginas; mantém históricos multilinha.
- Um valor sem sinal impresso à direita em continuação de página do Mercado Pago
  é candidato explícito, nunca fallback genérico ao saldo. Exige justificativa
  documental individual; saldos com sinal não são usados para preencher valores.
  A conferência exibe essa hipótese separadamente da leitura principal.
- No Mercado Pago de referência, a primeira operação da página 2 tem a coluna
  Valor vazia. A hipótese deslocada não é um valor confirmado. Revisar apenas
  os outros 22 registros não resolve essa pendência. O leitor alternativo em
  `native_readers.py` mantém essa ocorrência sem valor, em vez de propor hipótese.
- Os demais leitores não foram reescritos. Isso é preservação de código,
  não uma certificação de exatidão dos outros 18 gabaritos não revisados.
- Falhas sem registro utilizável permanecem na auditoria. O botão "Conferir
  ocorrência sem registro" permite preencher apenas ocorrências detectadas,
  abrindo o PDF e exigindo data, valor, histórico e justificativa. Pendências
  documentais sem ocorrência identificada exigem correção do leitor.
- A janela Tkinter foi validada em Linux com Tk 8.6 e display virtual Xvfb.
  A abertura externa do PDF foi conferida com MuPDF X11 configurado para o teste.
  Isso não certifica Windows, Excel/Calc nem homologa os leitores.
- Nenhum saldo é usado para corrigir ou selecionar valores.
- O teste monetário anterior de 4× acertou 493/500, não 100%. Não trocar a leitura
  principal indiscriminadamente por alta resolução.

Não usar esta candidata como importador homologado em produção.

## Validação desktop

Relatório e limites: [VALIDACAO_DESKTOP.md](VALIDACAO_DESKTOP.md).
O lançador `bash importador_dominio/tests/run_desktop_checks.sh` preservado
da versão principal executa os cenários de `tests/desktop_flow.py`, isolando
o ajuste de bibliotecas Nix no processo temporário.
Os testes usam widgets Tk reais e são opcionais para não impedir a execução
dos testes de leitores em máquinas sem interface:

```sh
RUN_DESKTOP_TESTS=1 python -m unittest discover -s importador_dominio/tests -v
```

É obrigatório usar um Python com o módulo nativo `_tkinter` e um display
funcional. Em Linux sem monitor, pode-se iniciar `Xvfb :97 -screen 0 1440x1000x24
-nolisten tcp` e executar com `DISPLAY=:97`. Instalar apenas Tcl/Tk não
necessariamente habilita Tkinter no Python já instalado.
Para capturas locais, acrescente
`DESKTOP_EVIDENCE_DIR=generated-artifacts/desktop-validation`;
esse recurso usa o comando `import` do ImageMagick.

Todos os leitores da candidata, inclusive os nativos, marcam os lançamentos
como pendentes de conferência individual. Fechar a janela ou usar “Cancelar”
não confirma nem modifica o lançamento. “Limpar” pede confirmação e inicia
uma sessão sem a trilha anterior. A exportação exige ausência de pendências
e estado de conferência explicitamente aprovado em todos os registros.

## Resultado desta validação (documentos de referência)

- Santander: 500 candidatos/500 ocorrências esperadas; 491 registros integralmente
  correspondentes após normalizar acentos/caixa/espaços; 499 valores corretos;
  0 datas divergentes, 1 valor e 8 históricos divergentes. Sem ausências/extras.
- Asaas: 22 candidatos/22 ocorrências esperadas; 19 correspondências integrais
  por multiconjunto página/data/valor/histórico, 22 correspondências monetárias
  por multiconjunto página/data/valor. Permanecem três históricos divergentes.
- Cora: 303/303 ocorrências e registros; nenhuma diferença em data, valor,
  categoria, contraparte e CPF/CNPJ. Mercado Pago: 23/23 ocorrências e candidatos;
  nenhuma diferença em data, valor e histórico; uma hipótese de valor deslocado
  permanece bloqueada para conferência. Repetições são comparadas por página e
  posição da ocorrência, sem deduplicação nem ajuste por saldo.
- Reproduzir a regressão diretamente nos PDFs e no gabarito revisado:
  `OMP_THREAD_LIMIT=1 RUN_DOCUMENT_REGRESSION=1 uv run python -m unittest discover -s importador_dominio/tests -v`.
  Requer o corpus original em `.local/conversation-workspace/files/attached_assets/`.
  Relatório gerado em `generated-artifacts/regression-cora-mercado.json` (fora do Git).
- Na regressão dos leitores alternativos preservados, Mercado Pago tem 23
  ocorrências e 22 registros correspondentes; o valor da primeira ocorrência da
  página 2 fica desconhecido. Esse resultado não deve ser confundido com a
  hipótese explícita do leitor ativo.
- Estes resultados não equivalem a homologação nem comprovam outros layouts.
- Os quatro bancos e a interface inteira ainda não foram integralmente homologados.
