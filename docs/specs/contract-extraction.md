# Extração de dados de contrato (PDF → dados estruturados)

Status: **rascunho v3** — validado em 4 contratos reais (PF+fiador x3, PJ+caução x1) e agora
**integrado de ponta a ponta com o frontend** (upload na tela → extração → edição → salva no
Supabase). Pendente de decisões listadas em "Limitações e pendências" antes de considerar isso
pronto para os 12 contratos.

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
- `app/api/main.py`, `app/api/routers/contracts.py` — endpoint HTTP síncrono (`POST
  /contracts/extrair`) que expõe `extrair_dados_contrato` pra rede. Não fala com o Supabase —
  só extrai e devolve JSON (ver "Endpoint HTTP" e "Integração com o frontend" abaixo).
- `tests/test_contract_models.py`, `tests/test_contract_extraction.py`,
  `tests/test_contracts_endpoint.py` — 19 testes unitários, sem custo de API (validadores
  Pydantic + chamada à Claude mockada + `TestClient` do FastAPI).

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

## Endpoint HTTP (`POST /contracts/extrair`)

Multipart form com um campo (`arquivo`, o PDF). Devolve o `ExtracaoContratoResult` como JSON —
**não grava nada no Supabase**, só extrai. Quem persiste é o frontend (ver seção seguinte).

Decisões de design:
- **Síncrono, não assíncrono/fila** — decisão consciente: contratos são subidos um de cada vez por
  um humano que pode esperar de segundos a alguns minutos. Se isso virar um problema real (ex:
  processamento em lote dos contratos restantes), dá pra migrar pra `arq`/`redis` (já estão no
  `requirements.txt` pra outros jobs futuros) sem redesenhar a extração em si.
- **Handler `def` síncrono, não `async def`** — `extrair_dados_contrato` bloqueia por até ~3
  minutos fazendo streaming pra Claude. Um handler `async def` chamando isso direto travaria o
  event loop inteiro do FastAPI (inclusive outros endpoints, tipo o futuro webhook do WhatsApp
  nesse mesmo app). Com `def` simples, o Starlette roda automaticamente numa threadpool.
- **Erros**: `content_type != application/pdf` → 415. Qualquer `RuntimeError` de
  `extrair_dados_contrato` (recusa da Claude, truncamento por `max_tokens`, `clausulas` vazia
  após retries) → 422 com o detalhe original na resposta.
- **CORS**: `app/api/main.py` libera `http://localhost:8080` explicitamente (origem do frontend em
  dev). Precisa atualizar essa lista quando o frontend for pra produção.

## Integração com o frontend (Lovable)

**Achado importante ao planejar essa integração**: o frontend
(`frontend/src/components/gestao/ContratosSection.tsx`) já tinha o fluxo inteiro pronto — upload de PDF (3 passos: upload → conferir
→ editar/salvar), campo de WhatsApp, e o **insert direto no Supabase** (`contracts` +
`contract_clauses`, sempre com `status: 'pendente_confirmacao'`) usando a própria sessão
autenticada da gestora logada. RLS (`staff_full_access`, `002_auth_rbac_rls.sql`) já dá acesso
total de leitura/escrita pra qualquer staff logado nessas duas tabelas — não precisa de
`service_role` nem de o backend gravar nada.

A única peça que faltava era a função `extrairDadosDoContrato()`, que estava mockada com dados
fake. Trocada por um `fetch()` real pro endpoint acima:

```ts
const formData = new FormData();
formData.append("arquivo", arquivo);
const response = await fetch(`${import.meta.env.VITE_API_URL}/contracts/extrair`, {
  method: "POST",
  body: formData,
});
```

`VITE_API_URL` é variável de ambiente nova (`frontend/.env`, default `http://localhost:8000` em
dev). Os nomes de campo em `ContratoExtraido`/`ClausulaExtraida` no TypeScript já batiam 1:1 com o
Pydantic — confirmado, não precisou de nenhuma tradução de formato. Importante: a tela só **mostra**
um resumo de ~6 campos pra conferência rápida (Passo 2/3), mas o insert manda o objeto inteiro
(`{...dados}`) — todos os campos extraídos são gravados, mesmo os sem campo próprio na tela. O
mesmo vale pras cláusulas: todas as que a extração retornar são salvas, sem filtro de categoria.

**Bug encontrado durante o teste manual (não relacionado à extração)**:
`frontend/src/lib/supabase.ts` expunha o client Supabase no `window` em modo dev (pra login de teste via console),
sem checar se `window` existe — quebrava o SSR do TanStack Start com `ReferenceError: window is
not defined`. Corrigido com uma guarda (`typeof window !== "undefined"`).

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

### 1. Categoria de cláusula como "catch-all" — resolvido parcialmente (Migration 003)
O enum original (9 valores) não tinha opção para cláusulas de objeto do contrato, prazo/vigência,
alienação do imóvel, desapropriação, foro de eleição ou disposições finais — todas caíam
sistematicamente em `rescisao` (confirmado em 3 contratos independentes, mesmo padrão). Análise
completa, com exemplos reais dos 3 contratos, em `docs/specs/categorizacao-clausulas.md`.

Resolvido via `docs/schemas/003_ajusta_categorias_clausulas.sql`: adicionadas `prazo_vigencia`,
`alienacao` e `disposicoes_gerais` ao `CHECK constraint` de `contract_clauses.categoria`.
`CategoriaClausula` em `app/models/contract.py` já foi atualizado para bater com as 12 categorias.

**Ainda em aberto**: cláusulas de compliance corporativo (LGPD, Lei Anticorrupção — vistas no
contrato PJ) não têm categoria própria, caem em `disposicoes_gerais`. E o problema mais estrutural
identificado na análise — cláusulas numeradas compostas (um único número do contrato cobrindo
vários assuntos, ex: "Uso do Imóvel" misturando rescisão + sublocação + desapropriação) — não foi
resolvido por essa migration, porque `categoria` continua sendo um valor único por cláusula. Ver
"Opções para resolver" em `categorizacao-clausulas.md` para as alternativas discutidas.

### 2. `telefone_whatsapp` não é extraído — resolvido (não é responsabilidade da extração)
Coluna `not null` em `contracts`, mas não existe no PDF do contrato — é dado operacional. Não
precisou virar problema da extração/endpoint: o campo é coletado numa tela própria do frontend
(Passo 3, depois da extração) e vai direto pro insert que o próprio frontend faz no Supabase — o
endpoint de extração nunca vê esse campo.

`locatario_endereco` e `fiador_endereco` (colunas novas da Migration 003) são diferentes — esses
**sim** costumam aparecer no PDF (endereço residencial das partes, na qualificação do contrato) e
já foram adicionados a `ContratoExtraido`. Testados e confirmados em extrações reais.

### 3. Não-determinismo do modelo
Observado repetidas vezes: mesma chamada (mesmo PDF, mesmo prompt) retornando `clausulas: []`
sem erro — resultado sintaticamente válido, mas semanticamente errado (contrato real sempre tem
cláusulas). Mitigado com retry automático em `extrair_dados_contrato` (`max_tentativas=2`, levanta
`RuntimeError` se persistir). Categorização de cláusulas-fronteira (ex: 2.2, 4.6) também variou
entre chamadas idênticas — `categoria` deve ser tratado como filtro auxiliar, não dado 100% estável.

**Achado durante o teste manual do endpoint**: o contrato 01 (Parnamirim), que sempre extraiu bem
antes, falhou 4 vezes seguidas (`clausulas: []` mesmo após retry) num teste recente — incluindo uma
tentativa direto pelo CLI, sem passar pelo endpoint novo, confirmando que não é bug do endpoint.
Diagnóstico da resposta bruta mostrou `stop_reason: tool_use` com só ~980 tokens de saída (não é
truncamento por `max_tokens` — o modelo genuinamente parou de gerar depois do campo `contrato`,
sem escrever `clausulas`). Um contrato diferente (02) funcionou de primeira logo em seguida. Sem
explicação definitiva — pode ser flutuação normal da API, ou alguma interação com o prompt mais
longo depois de adicionarmos a instrução de quebrar cláusulas em sub-itens. Vale monitorar se a
taxa de falha aumentou de fato ou se foi só uma sequência de azar.

### 4. `strict: true` (structured outputs) não é viável
O schema completo (contrato + lista de cláusulas) excede o limite de complexidade da API para
tool use estrito ("Schema is too complex"). Sem strict mode, não há garantia sintática de que a
resposta bata exatamente com o schema — daí o wrapper `_extrair_payload()` que desembrulha
qualquer chave extra que a Claude adicione por conta própria.

### 5. Rate limit da conta atual — resolvido
A conta estava limitada a ~10.000 tokens de entrada/minuto — abaixo até do tier "Start" oficial
(2.000.000), causando 429 mesmo em chamadas isoladas para o contrato maior (ARCO, ~2,2x o tamanho
dos outros). Resolvido adicionando forma de pagamento em console.anthropic.com/settings/billing —
conta migrou para o tier Start automaticamente.

### 6. Cobertura de teste — PJ e caução validados
Testado com sucesso um 3º contrato: locatário PJ (`tipo_locatario='pj'`, com
`responsavel_contato_nome` capturado corretamente), garantia por caução (`garantia_tipo='caucao'`,
`garantia_valor` preenchido, sem exigir fiador). Achado à parte durante esse teste: o comentário
antigo do schema sobre o ARCO ser "isento de multa moratória" estava incorreto — corrigido na
Migration 003, mas o valor exato (1% combinado ou 1%+1% empilhado com juros) continua pendente de
confirmação com o cliente antes de carregar os dados desse contrato específico.

Testado com sucesso um 4º contrato fora dos templates "Golden Beach"/"Parnamirim" (endereço
"Estrada das Ubaias, 20") — mesma estrutura de cláusulas numeradas, então ainda não prova
generalização pra um formato de contrato genuinamente diferente. Faltam 8 dos 12 contratos.

### 7. Persistência no Supabase — resolvido, mas não como esperado
A suposição original era que o backend gravaria em `contracts`/`contract_clauses` usando a
`service_role` key. Na prática, **o frontend já tinha esse fluxo pronto**: ele grava direto no
Supabase usando a própria sessão autenticada da gestora (RLS `staff_full_access` já dá acesso
total pra staff logado — não precisa de `service_role` nem de o backend fazer isso). O endpoint
novo (`POST /contracts/extrair`) só extrai e devolve JSON; quem persiste é o
`ContratosSection.tsx`, que já fazia `status: 'pendente_confirmacao'` no insert. Ver "Integração
com o frontend" acima.

## O que já está validado
- Extração completa de cláusulas, incluindo sub-itens numerados/em alíneas quebrados em entradas
  separadas (após corrigir prompt que estava pulando cláusulas "redundantes" e depois agrupando
  sub-itens compostos)
- Encoding UTF-8 correto na saída (bug de codepage do Windows corrigido)
- Validações de negócio via Pydantic (fiador, caução, datas) funcionando como trava antes de
  qualquer gravação, incluindo o caso PJ + caução (não exige fiador)
- Enum de categorias atualizado para as 12 categorias da Migration 003 — confirmado reduzindo
  drasticamente o catch-all em `rescisao` num reteste do contrato ARCO
- Endpoint `POST /contracts/extrair` funcionando de ponta a ponta: testado via `curl` direto e via
  upload real na tela do Lovable (com CORS liberado pra `localhost:8080`)
- 19 testes unitários cobrindo validadores, lógica de retry/erro e o endpoint HTTP (mockado, sem
  custo de API)
