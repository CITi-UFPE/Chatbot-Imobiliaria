# Testes de integração (A1–A5)

Diferente de `tests/` (unitários, `supabase.create_client`/`anthropic.Anthropic` sempre mockados), esta suíte fala com um projeto **Supabase de teste real** — Postgres de verdade, RLS de verdade, triggers e RPCs de verdade. É o único lugar que pega o tipo de bug mais caro do projeto: uma política de RLS bloqueando (ou deixando passar) um insert que o mock deixava passar, um enum do banco divergente do `Literal` em Python, uma constraint que não dispara como esperado, ou uma RPC (`agent_create_escalation`, `agent_finalizar_contrato`, ...) com efeito colateral que só existe no SQL.

Sem `.env.test` preenchido, **toda a suíte é pulada** (não falha "quebrada") — ver `_validar_ambiente_de_teste` em `conftest.py`. Por isso ela não entra no CI padrão: precisa dos secrets de um projeto Supabase dedicado, que não existe automaticamente em todo ambiente.

## 1. Provisionar o projeto Supabase de teste

1. Crie um projeto Supabase **novo e separado** do de produção, mesma região (`sa-east-1` — ver `docs/setup-supabase.md`, seção 1). Nunca reutilize o projeto de produção aqui: os testes fazem `delete` de contratos fictícios e mutam estado (finalização automática, negociação) — não é algo que se queira perto de dado real.
2. No **SQL Editor** do novo projeto, rode todas as migrations de `docs/schemas/001_create_tables.sql` até `019_normalizacao_telefone.sql`, **em ordem** (há dois arquivos históricos `018` e ambos vêm antes da `019`; várias migrations posteriores dependem de função/coluna criada nas anteriores — ver a lista comentada em `docs/setup-supabase.md`, seção 2). Alternativa via `psql`, uma vez que você tenha `SUPABASE_TEST_DB_URL` (passo 3):

   ```bash
   for f in docs/schemas/0*.sql; do
     echo "=== $f ==="
     psql "$SUPABASE_TEST_DB_URL" -v ON_ERROR_STOP=1 -f "$f" || break
   done
   ```
3. Configure a Standby Key HS256 do projeto de teste (Settings → JWT Keys → "Create a new Standby Key" → "Import an existing secret") — mesmo processo de `docs/setup-supabase.md`, seção 5, só que gerando/importando um segredo **novo**, nunca o de produção.

## 2. Configurar `.env.test`

Copie `.env.test.example` (raiz do repo) para `.env.test` e preencha a partir do dashboard do projeto de teste:

| Variável | Onde encontrar |
|---|---|
| `SUPABASE_TEST_URL` | `https://<Project ID>.supabase.co` do projeto de teste |
| `SUPABASE_TEST_ANON_KEY` | Settings → API Keys → "Publishable key" |
| `SUPABASE_TEST_SERVICE_ROLE_KEY` | Settings → API Keys → "Secret key" |
| `SUPABASE_TEST_JWT_SECRET` | O segredo da Standby Key HS256 criada no passo 1.3 |
| `SUPABASE_TEST_DB_URL` | Settings → Database → Connection string → URI (só para aplicar as migrations via `psql`; a aplicação em si nunca fala Postgres direto, sempre REST/PostgREST via `supabase-py`, igual produção) |

`conftest.py` carrega **só** `.env.test` (com `override=True`) e mapeia `SUPABASE_TEST_*` para `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`SUPABASE_JWT_SECRET` — as mesmas variáveis que o código de produção em `app/` já lê. Isso garante que os testes nunca conversam com o projeto de produção por engano, mesmo que o `.env` de produção já esteja carregado no ambiente.

Também é preciso de `ANTHROPIC_API_KEY` no ambiente (ou em `.env`, que continua sendo carregado normalmente pelo resto da aplicação) — ver seção de custo abaixo.

## 3. Rodar

```bash
pip install -r requirements.txt
pytest -m integration -v
```

A suíte unitária (`pytest tests/ -m "not integration"`) continua isolada e não precisa de nenhuma credencial de teste.

## 4. Nota de custo — chamadas reais à Anthropic

A1 (`test_a1_atendimento_integration.py`), A3 (`test_a3_manutencao_integration.py`, etapa de classificação da descrição) e A5 (`test_a5_escalonamento_integration.py`) fazem chamadas reais ao modelo `claude-sonnet-5` — não dá pra mockar isso sem perder exatamente o que a suíte deveria comprovar (que o loop de tool-use/classificação de fato funciona contra o schema real). Evite rodar essa parte da suíte em excesso fora de quando for necessário (ex: antes de um PR que mexeu em A1/A3/A5, não em todo `git commit`).

A2 (`test_a2_cobranca_integration.py`) e A4 (`test_a4_gestao_contratual_integration.py`) são puro cron/Postgres — sem custo de API, seguros de rodar com frequência. `test_rls_isolamento.py` também não usa Claude.

## 5. Fixtures (`fixtures/contratos.py`)

8 contratos fictícios, `function`-scoped (criados e apagados a cada teste, telefone `+551199990NN`), mesmo shape do insert do UploadWizard (`frontend/src/components/gestao/ContratosSection.tsx`):

| # | Fixture | Cenário |
|---|---|---|
| 1 | `contrato_pf_padrao` | PF padrão — caminho feliz do A1 (cláusula real) e A2 (D-5/D0) |
| 2 | `contrato_pj_caucao` | PJ/caução (ARCO) + charge de água já processada (`consumo_m3`, `charges_unico_por_mes`) |
| 3 | `contrato_prazo_indeterminado` | Prazo indeterminado (padrão Elias) — A4 pula alerta de renovação e finalização |
| 4 | `contrato_para_negociacao` | Charge em aberto — A5 detecta `desconto_renegociacao` e aciona `pausar_charges_em_negociacao` |
| 5 | `contrato_prestes_a_vencer` | `data_termino` = hoje+60 — alerta D-60 e finalização automática no término |
| 6 | `contrato_para_escalonamento` | Escalonamento simples (motivo ≠ `desconto_renegociacao`) — protocolo sequencial |
| 7 | `contrato_para_manutencao` | Ciclo completo da máquina de estados do A3 |
| 8 | `contrato_outro_para_isolamento` | Segundo contrato "qualquer", só para os testes de isolamento por RLS |
| 9 | `contrato_telefone_movel_legado` | Telefone móvel gravado com apresentação e sem nono dígito |
| 10 | `contrato_telefone_fixo` | Telefone fixo, sem geração de variante móvel |

Limpeza: cada fixture apaga seu próprio contrato ao final (o `on delete cascade` até `contracts` cuida do resto — charges, cláusulas, escalations, tickets, alerts, logs, estado de conversa). Uma fixture de sessão (`_limpeza_defensiva_de_sessao`) também limpa qualquer telefone órfão do intervalo `+551199990001`–`019` e os números dedicados à normalização antes e depois da sessão inteira, cobrindo o caso de uma execução anterior ter quebrado no meio. A suíte pode ser rodada 2x seguidas sem reset manual do banco.

## 6. Cenários transversais (`test_rls_isolamento.py`)

Isolamento por RLS entre contratos (leitura direta de tabela E escrita via RPC), expiração do JWT do agente (`TTL_PADRAO_SEGUNDOS`), e isolamento de erro no processamento em lote do A4 (um contrato com falha de escrita não impede os demais no mesmo lote).
