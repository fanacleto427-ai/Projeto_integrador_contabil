# Origem e licença do OCR: condição para gerar a distribuição

## Estado real

**Não há runtime Windows aprovado ou binário Windows gerado neste repositório.**
O ambiente de trabalho é Linux. Há agora uma receita nativa de compilação dos
fontes revisados, executada pelo GitHub Actions. A presença dessa receita não
comprova uma geração em Windows. Não entregar o kit como distribuição pronta
antes de obter os relatórios positivos da execução.

## Caminho automatizado: compilar fontes revisados

`build_ocr.py` baixa fontes upstream com versão e SHA-256 fixados, compila
estaticamente e gera o inventário com textos integrais das licenças e avisos:

| Componente | Versão | Licença |
|---|---|---|
| Tesseract | 5.5.0 | Apache-2.0 |
| Leptonica | 1.85.0 | BSD-2-Clause |
| libpng | 1.6.44 | libpng-2.0 |
| zlib | 1.3.1 | Zlib |
| tessdata_fast/por | 4.1.0 | Apache-2.0 |

Essas licenças permitem distribuição binária com as condições descritas nos
próprios textos: preservar origem, avisos, atribuições e disclaimers; incluir
a licença Apache e NOTICE quando aplicável; identificar alterações de fontes.
Os fontes não são alterados; apenas as opções de compilação são selecionadas.
Os arquivos LICENSE/AUTHORS e `leptonica-license.txt` são copiados integralmente.
Não foi encontrado NOTICE na raiz dos snapshots revisados; caso apareça, a
receita bloqueia a geração até nova revisão.

A compilação usa MSVC/CRT estático e somente suporte PNG/zlib em Leptonica.
Não inclui ferramentas, testes, contrib do libpng, treino, OpenMP, curl,
libarchive, JPEG, GIF, TIFF, WebP ou OpenJPEG. Os leitores continuam enviando
ao pytesseract imagens PNG geradas pelo Pillow. Não se trata de um instalador
genérico de Tesseract para todos os formatos de imagem.

`dumpbin /DEPENDENTS` deve comprovar que o EXE depende apenas das bibliotecas
de sistema Windows enumeradas na receita. Dependência extra, inclusive uma
DLL de runtime C++, bloqueia o inventário e a distribuição.
Os termos do compilador instalado também continuam aplicáveis:
https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files

O workflow faz isso automaticamente. Para gerar localmente, é preciso Windows
x64, Visual Studio 2022 com C++ e CMake, além do Python/Tk usado pelo aplicativo:

```bat
py -3.13 windows\build_ocr.py --work-dir generated-artifacts\ocr-novo
py -3.13 windows\build_windows.py --ocr-bundle generated-artifacts\ocr-novo\runtime
```

O diretório `--work-dir` deve ser novo; a receita não apaga compilações anteriores.
Não há download de instaladores externos. Os hashes estão em `build_ocr.py`;
alterar versões exige revisar também os textos legais, dependências e opções.
Essa revisão é de origem/licença, não uma certificação de segurança ou acurácia.

## Fontes consultadas

- A documentação oficial lista as distribuições Windows mantidas por terceiros:
  https://tesseract-ocr.github.io/tessdoc/Installation.html
- Uma delas é UB Mannheim:
  https://github.com/UB-Mannheim/tesseract/releases/tag/v5.4.0.20240606
- Licença do motor nessa revisão: Apache-2.0:
  https://github.com/UB-Mannheim/tesseract/blob/v5.4.0.20240606/LICENSE
- O instalador também inclui DLLs e outros recursos. A licença Apache do
  Tesseract **não licencia automaticamente as DLLs**:
  https://github.com/UB-Mannheim/tesseract/blob/v5.4.0.20240606/nsis/tesseract.nsi
- Modelo português oficial, versão fixa de tessdata_fast:
  https://github.com/tesseract-ocr/tessdata_fast/blob/4.1.0/por.traineddata
- Licença desse repositório de modelos: Apache-2.0:
  https://github.com/tesseract-ocr/tessdata_fast/blob/4.1.0/LICENSE

Apache-2.0 exige fornecer a licença, preservar avisos aplicáveis e identificar
modificações; preservar NOTICE quando houver. A consulta desses textos não
constitui revisão das dependências de um instalador específico. Por isso a
receita automatizada compila a dependência mínima dos fontes, em vez de
baixar/executar um instalador ou redistribuir suas DLLs.

## Alternativa: runtime externo preparado pelo responsável pelo pacote

1. Obter um runtime Windows x64 de procedência conhecida e registrar versão,
   URL fixa, hashes publicados (quando disponíveis) e a receita/fonte da build.
   Verificar também suas dependências transitivas em Windows limpo.
2. Conferir as obrigações de cada EXE, DLL e recurso que será distribuído.
   Incluir os textos integrais de licenças, atribuições e NOTICE aplicáveis.
   Se houver obrigação de fornecer código-fonte, prover o correspondente
   conforme a licença; uma URL genérica não é substituto dessa obrigação.
3. Colocar `tesseract.exe`, todas as DLLs exigidas, `tessdata/por.traineddata`
   e documentos em uma pasta. O modelo deve ser compatível com o motor.
4. Criar `OCR_MANIFEST.json` conforme o contrato abaixo, após revisão real.
   Não marcar revisão concluída apenas para contornar o bloqueio.
5. Em Windows nativo x64 executar:

   ```bat
   py -3.13 windows\build_windows.py --ocr-bundle "C:\Pacotes\OCR revisado"
   ```

   Alternativamente a pasta padrão é `windows/ocr-runtime`, ignorada no Git.
   Isso é preparação do **construtor**, não configuração para o usuário final.

### Contrato do inventário

Objeto JSON UTF-8 com:

- `schema`: `1`.
- `redistribution_reviewed`: `true`, somente após a conferência.
- `review_notes`: texto explicando as fontes consultadas, obrigações,
  avisos aplicáveis, modificações e como elas são cumpridas.
- `files`: objeto com **todos** os caminhos relativos (separador `/`) e seus
  SHA-256 reais. Inclui documentos de licença e avisos; não inclui o próprio
  inventário. São obrigatórios `tesseract.exe` e `tessdata/por.traineddata`.
- `components`: lista de objetos com `name`, `version`, `source` (HTTPS,
  preferencialmente revisão fixa), `license` (identificador/expressão),
  `files` (caminhos pertencentes ao componente), `license_files` (lista não
  vazia com textos integrais) e `notice_files` (lista dos avisos; `[]` apenas
  quando a revisão confirmar que não há NOTICE aplicável).

Todo arquivo inventariado deve pertencer a pelo menos um componente ou ser um
de seus documentos de licença/aviso. Não são aceitos links, caminhos absolutos
ou travessias de diretório. Somente os arquivos inventariados são copiados.
O inventário é uma declaração auditável do responsável, **não uma assinatura
digital nem uma validação jurídica automática**. O gerador verifica estrutura,
presença e hashes; não decide se uma licença foi corretamente interpretada.

## Evidência exigida antes da entrega

- Gerar em Windows x64; extrair o ZIP e confirmar em uma máquina Windows limpa,
  sem Python/Tesseract instalado, executando o teste abaixo.
- O gerador testa uma cópia extraída em caminho com espaços e acentos,
  com PATH reduzido e sem variáveis de OCR herdadas.
- O programa deve reconhecer exatamente o texto sintético
  `AÇÃO, RECEBIMENTO E PAGAMENTO EM PORTUGUÊS` com `lang=por`.
- O gerador remove o motor apenas da cópia temporária e exige diagnóstico
  explícito de indisponibilidade, sem diálogo que bloqueie a automação.
- `VERIFICACAO_OCR.json` registra o resultado e a versão do Windows. A execução
  local do gerador não prova que a máquina estava limpa de DLLs adicionais.
  Registrar separadamente a execução da máquina limpa.

```bat
ImportadorDominio.exe --require-bundled-ocr --ocr-self-test ocr-maquina-limpa.json
```

O usuário final extrai a pasta inteira e executa o programa, sem instalar OCR
ou configurar caminhos. Variáveis explícitas `TESSERACT_CMD` e
`TESSDATA_PREFIX` prevalecem; se incorretas, são reportadas, não substituídas.
Ausência de OCR gera um aviso e não impede o uso dos leitores de texto nativo.
Nada aqui homologa extratos nem duplica os ensaios de abertura de PDF/cancelamento.
