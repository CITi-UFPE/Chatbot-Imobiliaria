# Extração de dados de contrato (PDF → dados estruturados)

Status: **rascunho v1** — validado em 2 contratos reais (mesmo template), pendente de decisões
listadas em "Limitações e pendências" antes de considerar isso pronto para os 12 contratos.

## Objetivo

Ler o PDF de um contrato de aluguel residencial e extrair, de forma estruturada, os campos que
alimentam a tabela `contracts` (e as cláusulas do contrato, para a tabela `contract_clauses`),
sem intervenção manual.

## Arquitetura

- `app/models/contract.py` — modelos Pydantic (`ContratoExtraido`, `ClausulaExtraida`,
  `ExtracaoContratoResult`) que espelham o schema SQL em `docs/schemas/001_create_tables.sql`.
  Validam localmente regras que o banco também vai exigir (ex: fiador precisa de nome+CPF,
  caução precisa de valor, término > início).
- `app/tools/contract_extraction.py` — chama a Claude API (tool use) passando o PDF como
  documento e o schema Pydantic como `input_schema` da tool. `extrair_dados_contrato(caminho_pdf)`
  retorna um `ExtracaoContratoResult` validado.
- `tests/test_contract_models.py`, `tests/test_contract_extraction.py` — 15 testes unitários,
  sem custo de API (validadores Pydantic + chamada à Claude mockada).

## Modelo usado

`claude-sonnet-5`. Motivo: extração de documento estruturado com PDF de várias páginas — precisa
de leitura de documento (suporte nativo a PDF) e tool use confiável; não é uma tarefa que exija
Opus, e não é simples o bastante pra confiar em Haiku sem validar antes.

## Fluxo de execução

1. PDF é lido e enviado em base64 como `document` content block.
2. Tool `registrar_dados_contrato` é forçada via `tool_choice`.
3. A resposta (`tool_use.input`) passa por `_extrair_payload()` antes de validar — necessário
   porque a Claude às vezes embrulha a resposta numa chave extra (`"dados"`) não prevista no
   schema (ver Limitações).
4. `ExtracaoContratoResult.model_validate(...)` valida tudo — se algo não bater com as regras
   de negócio (fiador sem CPF, datas invertidas, etc.), a extração falha aqui, antes de qualquer
   gravação.
5. Resultado salvo em `data/extracoes/<nome_do_pdf>.json` (pasta local, fora do git — contém PII
   real de inquilino/fiador).

## Custo por contrato

Medido em 2 execuções reais (mesmo contrato-modelo, ~9 páginas):

| Execução | input_tokens | output_tokens |
|---|---|---|
| 1 | 26.339 | 7.809 |
| 2 | 26.944 | 10.531 |

Com o preço promocional do Sonnet 5 (vigente até 31/08/2026 — $2/1M input, $10/1M output):
**~US$0,10–0,15 por contrato** (~R$0,50–0,75 à cotação de R$5,13/USD, 08/07/2026).

Após 31/08/2026 o preço sobe para $3/1M input, $15/1M output → **~US$0,15–0,22 por contrato**
(~R$0,75–1,15).

Para os 12 contratos, isso é uma execução única (não recorrente) — total estimado entre **R$6 e
R$14**, mais margem para retentativas (rate limit ou `clausulas` vazia — ver abaixo).

## Limitações e pendências conhecidas

### 1. Categoria de cláusula como "catch-all" (pendente de decisão)
O enum `categoria` (9 valores, espelhando o `CHECK constraint` do banco) não tem opção para
cláusulas de objeto do contrato, prazo/vigência, alienação do imóvel, desapropriação, foro de
eleição ou disposições finais. Essas caem sistematicamente em `rescisao` (confirmado em 2
contratos independentes, mesmo padrão). Descrever melhor cada categoria no prompt **não resolveu**
— só tornou o comportamento mais consistente, não mais preciso. Proposta enviada a quem fez o
schema: adicionar `prazo_vigencia` e `outros` ao enum (requer migration no Supabase).

### 2. `telefone_whatsapp` não é extraído
Coluna `not null` em `contracts`, mas não existe no PDF do contrato — é dado operacional que
precisa vir de outra fonte (cadastro do inquilino) na hora de gravar no Supabase. Não é um bug de
prompt/schema; é uma dependência externa que a etapa de persistência (ainda não implementada) vai
precisar resolver.

### 3. Não-determinismo do modelo
Observado pelo menos uma vez: mesma chamada (mesmo PDF, mesmo prompt) retornando `clausulas: []`
sem erro — resultado sintaticamente válido, mas semanticamente errado (contrato real sempre tem
cláusulas). Mitigado com retry automático em `extrair_dados_contrato` (`max_tentativas=2`, levanta
`RuntimeError` se persistir). Categorização de cláusulas-fronteira (ex: 2.2, 4.6) também variou
entre chamadas idênticas — `categoria` deve ser tratado como filtro auxiliar, não dado 100% estável.

### 4. `strict: true` (structured outputs) não é viável
O schema completo (contrato + lista de cláusulas) excede o limite de complexidade da API para
tool use estrito ("Schema is too complex"). Sem strict mode, não há garantia sintática de que a
resposta bata exatamente com o schema — daí o wrapper `_extrair_payload()` que desembrulha
qualquer chave extra que a Claude adicione por conta própria.

### 5. Rate limit da conta atual
A conta usada nos testes está limitada a ~10.000 tokens de entrada/minuto — abaixo até do tier
"Start" oficial (2.000.000). Uma única chamada (~27.000 tokens) já é maior que esse limite,
tornando testes em sequência não-confiáveis. Resolver antes de processar os 12 contratos em lote
(adicionar forma de pagamento em console.anthropic.com/settings/billing deve colocar a conta no
tier Start automaticamente).

### 6. Cobertura de teste parcial
Só testamos contratos PF + fiador (2 amostras, mesmo template — "Domingos Monteiro"). Ainda não
testamos: locatário PJ (`tipo_locatario='pj'`, com `responsavel_contato_nome`), garantia por
caução (`garantia_tipo='caucao'`, com `garantia_valor`), ou contratos que fujam do template padrão.

### 7. Persistência no Supabase — não implementada
Hoje o script só valida e salva localmente em `data/extracoes/`. Não grava em `contracts` nem
`contract_clauses`. A coluna `status` já tem default `'pendente_confirmacao'`, sugerindo o fluxo
pretendido: extrair → gravar como pendente → humano confirma no Lovable → status vira `'ativo'`.
Essa etapa ainda não existe.

## O que já está validado
- Extração completa de cláusulas (após corrigir prompt que estava pulando cláusulas "redundantes")
- Encoding UTF-8 correto na saída (bug de codepage do Windows corrigido)
- Validações de negócio via Pydantic (fiador, caução, datas) funcionando como trava antes de
  qualquer gravação
- 15 testes unitários cobrindo validadores e lógica de retry/erro (sem custo de API)
