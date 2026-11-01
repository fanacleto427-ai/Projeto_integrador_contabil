# Gerar o executável Windows

**Este kit contém o código e o gerador, não um `.exe` já compilado.**
A compilação exige Windows nativo. Não renomeie um programa Linux para `.exe`.
A candidata continua **não homologada**; empacotar não corrige a precisão bancária.

## Passos

1. Extraia todo o ZIP numa pasta sua, com permissão de escrita.
2. Instale Python **64 bits**, versão 3.11 ou superior, com Tcl/Tk.
   Recomendado: Python 3.13. Se usar o comando `python`, marque a opção PATH.
3. Dê dois cliques em **`GERAR_EXE_WINDOWS.bat`** na pasta que contém `app.py`.
   É necessária internet: o comando instala as dependências de
   `requirements.txt` e PyInstaller no Python selecionado. Não precisa instalar
   PyInstaller manualmente. Não desative o antivírus.
   Antes, o responsável pela geração deve compilar o runtime com
   `windows/build_ocr.py` ou fornecer um runtime OCR revisado, como descrito em
   [OCR_REDISTRIBUICAO.md](OCR_REDISTRIBUICAO.md). Sem esse runtime o gerador
   bloqueia a distribuição. O GitHub Actions faz a preparação automaticamente.
4. Aguarde a mensagem de conclusão. Em caso de falha, leia o erro na janela;
   uma saída de geração anterior não confirma o sucesso da tentativa atual.
5. O arquivo para levar a outro computador estará em:
   **`generated-artifacts\windows\ImportadorDominio_Windows.zip`**.
6. Extraia esse ZIP e execute **`ImportadorDominio.exe`**.
   Não mova apenas o `.exe`: a pasta **`_internal`** deve permanecer ao lado dele.

Para selecionar uma versão específica do Python ou não reinstalar dependências:

```bat
py -3.13 windows\build_windows.py
py -3.13 windows\build_windows.py --skip-install
```

O gerador pode substituir saídas de compilação anteriores em
`generated-artifacts\windows`. Ele não altera PDFs, lançamentos, leitores
ou o arquivo original v1.12.

## OCR incluído na distribuição gerada

O gerador inclui o runtime revisado em `_internal/ocr`, com o idioma português
(`por`), suas DLLs, inventário de origem, licenças e avisos. O usuário final não
precisa instalar OCR ou Python nem configurar caminhos.

**Os scripts não comprovam sozinhos uma compilação Windows.**
São obrigatórios os relatórios da geração e da prova em outra máquina;
ver [OCR_REDISTRIBUICAO.md](OCR_REDISTRIBUICAO.md).

Na inicialização, `TESSERACT_CMD` explícito prevalece; sem ele, usa o OCR
incluído, depois PATH e locais usuais de instalação. `TESSDATA_PREFIX`
explícito também é preservado. Uma configuração explícita inválida gera
diagnóstico, nunca substituição silenciosa. A falta de OCR gera aviso; os
leitores de texto nativo continuam disponíveis.

## Alternativa: geração pelo GitHub Actions

O workflow está em `.github/workflows/build-windows.yml` no repositório
completo, com uma cópia para kits isolados em `windows/build-windows.yml`.
Ele prepara o OCR dos fontes com versões/hashes fixos e inclui as licenças;
não exige montagem manual de uma pasta de DLLs.

Para usar essa alternativa, coloque os fontes do kit num repositório seu
(preferencialmente privado, **sem PDFs ou dados bancários**) e copie o exemplo
para `.github/workflows/build-windows.yml` na raiz do repositório.
O exemplo aceita `app.py` na raiz ou dentro de `importador_dominio/`.
Na aba Actions, execute manualmente **Gerar Importador Dominio Windows**.
Um envio à branch `agent/windows-ocr` também inicia essa execução.
Após sucesso, baixe o artefato `ImportadorDominio-Windows-candidata`;
ele contém o ZIP da distribuição, seu SHA-256 e os relatórios. Esse artefato
final só é disponibilizado se a prova em outra VM Windows passar.

São três etapas: compilar/empacotar, verificar o ZIP em outra VM sem configurar
Python ou OCR e registrar os resultados. Apenas a etapa de registrar evidências
tem permissão de escrita, limitada pelo código à criação de uma branch
`ocr-evidence-<execução>` com JSON e trechos finais dos logs técnicos.
Os binários não são colocados no Git. A imagem `windows-2022` possui softwares
pré-instalados; é uma VM nova do GitHub, não uma instalação mínima do Windows.

Essa opção exige conta/repositório GitHub e disponibilidade de runners Windows,
sujeita às permissões, políticas e limites da sua conta. Este kit não cria
contas, repositórios, tokens ou cobranças nem envia arquivos automaticamente.

## O que o gerador confere

- Hash da v1.12 antes e depois da compilação, inclusive no `_internal` distribuído.
- Recursos Tk, módulos dos quatro leitores, bibliotecas PDF/imagem/Excel.
- Abertura de janela Tk oculta e leitura/gravação de PDF e XLSX **sintéticos**.
- Integridade ZIP e SHA-256 do pacote.
- Origem/licenças declaradas, hashes e presença dos arquivos OCR.
- OCR português sintético em cópia extraída sem configuração externa;
  diagnóstico de motor ausente. Resultado em `VERIFICACAO_OCR.json`.

O resultado fica em `VERIFICACAO_EMPACOTAMENTO.json` na distribuição.
Isso **não testa PDFs reais, visualizador externo nem acurácia contábil**.
O OCR sintético não substitui a validação em uma máquina Windows limpa.
Se a verificação falhar, não é emitido um novo ZIP aprovado por esse fluxo.
Logs do PyInstaller ficam no diretório de saída; falhas de inicialização
do executável são registradas em
`%TEMP%\ImportadorDominio_falha_inicializacao.log`.

## Limitações preservadas

Não há assinatura digital nem instalador. O Windows pode mostrar avisos de
aplicativo desconhecido; este kit não contorna essas proteções.

Continuam as pendências de OCR/históricos, a operação ambígua de Mercado Pago e
a necessidade de proteger a consistência da planilha e da auditoria em caso de
falha de gravação. Nenhum saldo é usado para preencher um lançamento.
