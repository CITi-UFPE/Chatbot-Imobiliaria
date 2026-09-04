# A1 — Status de Cobrança (Contas em Aberto + Histórico de 30 Dias) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar a lacuna identificada em análise de código anterior — hoje o A1 (Atendimento ao Inquilino) não tem acesso a nenhum dado de status de cobrança (`charges`), então não consegue responder honestamente "existe alguma conta em aberto pro meu apartamento?". Este plano dá ao A1 uma nova RPC + tool para responder (1) quais cobranças estão em aberto e o status de cada uma, e (2) quais cobranças tiveram pagamento identificado nos **últimos 30 dias** — nunca um histórico completo.

**Architecture:** Nova RPC `buscar_status_cobranca_inquilino()` (Postgres, `security definer`, escopada por `agent_contract_id()`, mesmo padrão de `buscar_dados_inquilino`/`buscar_dados_cobranca_contrato`) lê a tabela `charges` — já com `GRANT select` e RLS (`agent_read_own_charges`) concedidos ao papel `agente_ia` desde a Migration 002, então nenhum GRANT/policy novo é necessário. O A1 ganha uma tool nova que chama essa RPC, valida o retorno via Pydantic, e o `SYSTEM_PROMPT` instrui o modelo a traduzir os status técnicos (`pendente`, `atrasado`, `aguardando_confirmacao`, `divergente`, `em_negociacao`) em linguagem simples, e a nunca afirmar nada sobre pagamento fora da janela de 30 dias.

**Tech Stack:** Python 3, Pydantic v2, `anthropic` SDK (tool-use), Supabase Postgres (PL/pgSQL, RLS), `supabase-py`, pytest (+ `pytest.mark.integration`).

**Spec:** Este documento é a própria spec — não há spec separada; os requisitos vieram diretamente do usuário nesta conversa (ver Global Constraints) e da análise de código já feita (lacuna confirmada em `docs/schemas/006_a1_rpcs.sql` e `app/agents/a1_atendimento/schemas.py`).

## Global Constraints

- Toda RPC nova é `security definer`, sem parâmetro de `contract_id`, escopada só via `agent_contract_id()` — mesma doutrina documentada em `app/agents/a1_atendimento/atendimento.py:18-26` e em toda RPC existente (`docs/schemas/006_a1_rpcs.sql`, `011_a2_cobranca_rpcs.sql`, `014_dados_pagamento_no_a1.sql`).
- Nenhum GRANT ou policy de RLS novo é necessário: `agente_ia` já tem `SELECT` em `charges` e a policy `agent_read_own_charges` desde `docs/schemas/002_auth_rbac_rls.sql`.
- Retorno de toda RPC nova é validado via `model_validate` do Pydantic ANTES de virar `tool_result` pro Claude — nunca repassar dict cru (mesmo padrão de `_executar_buscar_dados_inquilino`).
- Campos de data nos schemas do A1 ficam como `str` (não `date`), mesmo padrão de `DadosInquilino` (`app/agents/a1_atendimento/schemas.py:52-93`) — o Supabase já devolve ISO 8601 dentro do jsonb.
- **Regra explícita do usuário, não negociável:** o histórico de pagamento exposto ao A1 cobre APENAS cobranças com `data_pagamento` preenchida E dentro dos últimos 30 dias corridos (`current_date - 30`). Nunca apresentar isso como histórico completo nem inventar status de algo fora da janela.
- "Conta em aberto" = qualquer `charges.status` diferente de `confirmado`/`quitado` — mais amplo que a constante `STATUS_CHARGES_ABERTAS = ("pendente", "atrasado")` que o A2 usa para sua própria lógica de negócio interna (`app/agents/a2_cobranca/comprovante.py:67`, `cobranca.py:41`); aqui o objetivo é honestidade total com o inquilino, não replicar aquele filtro mais estreito.
- Linguagem de resposta ao inquilino: sempre parafraseada, nunca o valor cru do campo `status` nem jargão técnico — mesma regra da seção `## COMO RESPONDER` já existente no `SYSTEM_PROMPT` do A1.
- Migrations em `docs/schemas/NNN_slug.sql`, sempre `create or replace function` quando possível, `grant execute ... to agente_ia` explícito. Numeração pode colidir entre branches (já aconteceu antes, ver docstring de `docs/schemas/011_a2_cobranca_rpcs.sql`) — confirmar o próximo número livre antes de aplicar de verdade.

---

## File Structure

- `docs/schemas/023_status_cobranca_a1.sql` (novo) — a RPC `buscar_status_cobranca_inquilino()`.
- `app/agents/a1_atendimento/schemas.py` (modificado) — `TipoCobranca`, `StatusCharge`, `ChargeEmAberto`, `ChargePagaRecente`, `StatusCobrancaContrato`.
- `app/agents/a1_atendimento/atendimento.py` (modificado) — `TOOL_BUSCAR_STATUS_COBRANCA`, entrada em `_tools_schema()`, `_executar_buscar_status_cobranca()`, despacho no loop de tool-use, novas seções do `SYSTEM_PROMPT`.
- `app/orchestrator/classificador.py` (modificado) — exemplo explícito de "conta em aberto" no bullet do A1.
- `tests/test_a1_status_cobranca.py` (novo) — unitário, sem API/DB reais.
- `tests/test_a1_atendimento_prompt.py` (modificado) — regressão do `SYSTEM_PROMPT`/tool schema.
- `tests/test_classificador_intencao.py` (modificado) — regressão do `SYSTEM_PROMPT` do classificador.
- `tests/integration/test_a1_status_cobranca_integration.py` (novo) — ponta a ponta com Supabase de teste + Claude real.
- `docs/setup-supabase.md` (modificado) — changelog da migration 023.
- `tests/integration/README.md` (modificado) — estende a instrução de "rode as migrations até NNN" e adiciona verificação da nova RPC.

---

### Task 1: Migration SQL — RPC `buscar_status_cobranca_inquilino`

**Files:**
- Create: `docs/schemas/023_status_cobranca_a1.sql`
- Modify: `docs/setup-supabase.md:39` (após a linha da Migration 021, antes de "**Rodar sempre nessa ordem**")
- Modify: `tests/integration/README.md` (seção "## 1. Provisionar o projeto Supabase de teste")

**Interfaces:**
- Produces: RPC Postgres `buscar_status_cobranca_inquilino() returns jsonb`, sem parâmetros, chamável via `client.rpc("buscar_status_cobranca_inquilino", {}).execute()`. Formato do jsonb:
  ```json
  {
    "charges_abertas": [
      {"charge_id": "uuid", "tipo": "aluguel|agua", "mes_referencia": "YYYY-MM-DD",
       "valor_esperado": 1500.0, "data_vencimento": "YYYY-MM-DD",
       "dias_atraso": 0, "status": "pendente|aguardando_confirmacao|divergente|atrasado|em_negociacao"}
    ],
    "charges_pagas_ultimos_30_dias": [
      {"charge_id": "uuid", "tipo": "aluguel|agua", "mes_referencia": "YYYY-MM-DD",
       "valor_esperado": 1500.0, "valor_identificado": 1500.0 | null,
       "data_pagamento": "YYYY-MM-DD", "status": "confirmado|quitado"}
    ]
  }
  ```

- [ ] **Step 1: Escrever a migration**

```sql
-- ============================================================
-- MIGRATION 023 — Status de cobrança para o A1 (contas em aberto +
-- histórico de pagamento recente)
-- ============================================================
-- ATENÇÃO — confira o próximo número livre antes de rodar: este arquivo foi
-- escrito com docs/schemas/022_resposta_gestora_escalonamento.sql como o
-- mais recente aplicado. Já houve colisão de numeração antes entre branches
-- (ver docstring da Migration 011) — se outra branch já ocupou "023" nesse
-- meio tempo, renumere antes de aplicar.
--
-- Depende das Migrations 001 e 002 já terem rodado (agent_contract_id(),
-- tabela charges, GRANT select em charges pro papel agente_ia e a policy
-- agent_read_own_charges — todos já existentes desde a Migration 002,
-- nenhum GRANT/policy novo precisa ser criado aqui).
--
-- Lacuna que esta migration fecha: buscar_dados_inquilino (Migration 006/
-- 014) só consulta contracts + contract_clauses — nunca devolveu o status
-- real de cobrança (tabela charges), que é domínio do A2. Só que o A2 nunca
-- reage a texto livre do inquilino (só comprovante/clique de botão/cron —
-- ver app/orchestrator/orchestrator.py), então "tem alguma conta em aberto
-- pro meu apartamento?" não tinha resposta em lugar nenhum do sistema —
-- mesmo formato de lacuna que a Migration 014 já resolveu para dados
-- bancários (Pix/banco).
--
-- Decisão de escopo, a pedido explícito do usuário: charges_abertas devolve
-- TODAS as cobranças que não estão pagas/confirmadas (qualquer status
-- diferente de 'confirmado'/'quitado') — não só ('pendente','atrasado')
-- como a constante STATUS_CHARGES_ABERTAS do A2 (app/agents/a2_cobranca/
-- comprovante.py e cobranca.py) usa para sua lógica interna de negócio.
-- Aqui o objetivo é informar o inquilino com honestidade sobre QUALQUER
-- cobrança ainda em aberto (inclusive 'aguardando_confirmacao',
-- 'divergente', 'em_negociacao'), não replicar aquele filtro mais estreito.
--
-- charges_pagas_ultimos_30_dias é deliberadamente uma janela — não um
-- histórico completo: só cobranças com data_pagamento preenchida E dentro
-- dos últimos 30 dias corridos (current_date - 30). Cobranças confirmadas/
-- quitadas há mais tempo NÃO aparecem aqui; ver app/agents/a1_atendimento/
-- atendimento.py (SYSTEM_PROMPT) para a instrução de NUNCA inventar se algo
-- fora dessa janela foi pago.
--
-- Edge case aceito, não resolvido aqui: uma charge com status='confirmado'
-- mas data_pagamento NULA (comprovante com data ilegível — ver
-- app/agents/a2_cobranca/comprovante.py:_marcar_aguardando_confirmacao)
-- não aparece em NENHuma das duas listas. Fora de escopo desta migration;
-- documentado para não ser confundido com bug se aparecer em teste manual.
--
-- Padrão de hardening: security definer + set search_path = '' + tudo
-- schema-qualificado (public.charges, public.agent_contract_id()) — mesmo
-- padrão das 3 migrations mais recentes que criam função security definer
-- (019_normalizacao_telefone.sql, 020_whatsapp_janela_atendimento.sql,
-- 022_resposta_gestora_escalonamento.sql), não o padrão mais antigo
-- (006/011/014, sem search_path fixo) que uma migration nova não deve mais
-- replicar.
-- ============================================================

begin;

create or replace function public.buscar_status_cobranca_inquilino()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_contract_id uuid := public.agent_contract_id();
  v_abertas jsonb;
  v_pagas_recentes jsonb;
begin
  select coalesce(jsonb_agg(jsonb_build_object(
    'charge_id', ch.id,
    'tipo', ch.tipo,
    'mes_referencia', ch.mes_referencia,
    'valor_esperado', ch.valor_esperado,
    'data_vencimento', ch.data_vencimento,
    'dias_atraso', ch.dias_atraso,
    'status', ch.status
  ) order by ch.data_vencimento), '[]'::jsonb)
  into v_abertas
  from public.charges ch
  where ch.contract_id = v_contract_id
    and ch.status not in ('confirmado', 'quitado');

  select coalesce(jsonb_agg(jsonb_build_object(
    'charge_id', ch.id,
    'tipo', ch.tipo,
    'mes_referencia', ch.mes_referencia,
    'valor_esperado', ch.valor_esperado,
    'valor_identificado', ch.valor_identificado,
    'data_pagamento', ch.data_pagamento,
    'status', ch.status
  ) order by ch.data_pagamento desc), '[]'::jsonb)
  into v_pagas_recentes
  from public.charges ch
  where ch.contract_id = v_contract_id
    and ch.data_pagamento is not null
    and ch.data_pagamento >= (current_date - interval '30 days');

  return jsonb_build_object(
    'charges_abertas', v_abertas,
    'charges_pagas_ultimos_30_dias', v_pagas_recentes
  );
end;
$$;

revoke all on function public.buscar_status_cobranca_inquilino() from public;
grant execute on function public.buscar_status_cobranca_inquilino() to agente_ia;

comment on function public.buscar_status_cobranca_inquilino() is
  'Devolve cobrancas em aberto e pagamentos identificados nos ultimos 30 dias do contrato do JWT, para o A1 responder duvidas de status de cobranca sem depender do A2 (que nunca reage a texto livre).';

commit;

-- ============================================================
-- FIM DA MIGRATION 023
-- ============================================================
```

Salve isso em `docs/schemas/023_status_cobranca_a1.sql`. A qualificação `public.` não muda o nome que o `supabase-py` chama via RPC — `client.rpc("buscar_status_cobranca_inquilino", {})` continua igual (PostgREST expõe pelo nome da função, não pelo texto do `CREATE`).

- [ ] **Step 2: Atualizar o changelog em `docs/setup-supabase.md`**

Em `docs/setup-supabase.md`, logo após a linha que descreve `021_normalizacao_telefone.sql` (linha 39 — a última linha da lista, não a 31 como uma citação anterior deste plano dizia por engano) e antes da linha em branco seguida de `**Rodar sempre nessa ordem**...` (linha 41), adicione:

```markdown
- `023_status_cobranca_a1.sql` — nova RPC `buscar_status_cobranca_inquilino`, para o A1 responder se há alguma conta/cobrança em aberto (qualquer status diferente de `confirmado`/`quitado`) e o histórico de pagamento identificado nos últimos 30 dias. Fecha a mesma lacuna que a Migration 014 já resolveu para dados bancários, agora para status de cobrança (domínio antes exclusivo do A2, que nunca respondeu por texto).
```

- [ ] **Step 3: Atualizar `tests/integration/README.md`**

Na seção `## 1. Provisionar o projeto Supabase de teste`, item 2, troque a frase "rode todas as migrations de `docs/schemas/001_create_tables.sql` até `021_normalizacao_telefone.sql`" por "rode todas as migrations de `docs/schemas/001_create_tables.sql` até `023_status_cobranca_a1.sql`" (mantendo o resto do parágrafo igual).

Logo após o item numerado 4 (verificação da `020_whatsapp_janela_atendimento.sql`), adicione um item 5:

```markdown
5. Verificação rápida de que a `023` foi aplicada — no **SQL Editor**:

   ```sql
   select proname from pg_proc where proname = 'buscar_status_cobranca_inquilino';
   ```

   Uma linha de retorno confirma a RPC presente; sem isso, os testes de
   `test_a1_status_cobranca_integration.py` (Task 6 deste plano) falham na
   consulta, não na lógica em si.
```

- [ ] **Step 4: Verificação manual (requer acesso ao Supabase de teste)**

Aplique o arquivo via SQL Editor do projeto Supabase de teste (ou `psql "$SUPABASE_TEST_DB_URL" -v ON_ERROR_STOP=1 -f docs/schemas/023_status_cobranca_a1.sql`) e rode:

```sql
select proname from pg_proc where proname = 'buscar_status_cobranca_inquilino';
```

Expected: 1 linha de retorno. Sem acesso ao projeto de teste nesta sessão, esta etapa fica pendente para quem tiver as credenciais (`tests/integration/README.md`, seção 2) — os Tasks 2-5 (unitários) não dependem disso; o Task 6 (integração) sim.

- [ ] **Step 5: Commit**

```bash
git add docs/schemas/023_status_cobranca_a1.sql docs/setup-supabase.md tests/integration/README.md
git commit -m "feat(db): RPC buscar_status_cobranca_inquilino para o A1"
```

---

### Task 2: Schemas Pydantic do A1 para status de cobrança

**Files:**
- Modify: `app/agents/a1_atendimento/schemas.py:1-105` (adiciona ao final do arquivo)
- Test: `tests/test_a1_status_cobranca.py` (novo — cria neste task só a parte de schema; a parte de `atendimento.py` entra no Task 3)

**Interfaces:**
- Consumes: nenhuma (schemas puros).
- Produces: `TipoCobranca: Literal["aluguel", "agua"]`, `StatusCharge: Literal[...]` (7 valores, mesmos da Migration 001/`charges.status` check constraint), `ChargeEmAberto`, `ChargePagaRecente`, `StatusCobrancaContrato(charges_abertas: list[ChargeEmAberto], charges_pagas_ultimos_30_dias: list[ChargePagaRecente])` — Task 3 importa `StatusCobrancaContrato` de `app.agents.a1_atendimento.schemas`.

- [ ] **Step 1: Escrever o teste de validação do schema (falha primeiro)**

Criar `tests/test_a1_status_cobranca.py` (os novos modelos entram no final de `schemas.py`, depois da classe `RegistroHistorico`, que termina na linha 106 — não 105):

```python
"""Testes da tool buscar_status_cobranca_inquilino do A1 (Atendimento).

Não chama a API da Anthropic nem o Supabase de verdade — só a função Python
que embrulha a RPC (_executar_buscar_status_cobranca) e a validação
Pydantic do retorno, mesmo padrão de tests/test_classificador_intencao.py e
tests/test_a1_atendimento_prompt.py (nenhum dos dois precisa de
ANTHROPIC_API_KEY nem de Supabase real)."""

import pytest
from pydantic import ValidationError

from app.agents.a1_atendimento.schemas import StatusCobrancaContrato


def test_status_cobranca_contrato_aceita_retorno_valido():
    dados = {
        "charges_abertas": [
            {
                "charge_id": "c1",
                "tipo": "aluguel",
                "mes_referencia": "2026-09-01",
                "valor_esperado": 1500.0,
                "data_vencimento": "2026-09-10",
                "dias_atraso": 3,
                "status": "atrasado",
            }
        ],
        "charges_pagas_ultimos_30_dias": [
            {
                "charge_id": "c2",
                "tipo": "agua",
                "mes_referencia": "2026-08-01",
                "valor_esperado": 120.5,
                "valor_identificado": 120.5,
                "data_pagamento": "2026-08-20",
                "status": "confirmado",
            }
        ],
    }

    validado = StatusCobrancaContrato.model_validate(dados)

    assert validado.charges_abertas[0].status == "atrasado"
    assert validado.charges_pagas_ultimos_30_dias[0].data_pagamento == "2026-08-20"


def test_status_cobranca_contrato_aceita_listas_vazias():
    validado = StatusCobrancaContrato.model_validate(
        {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}
    )
    assert validado.charges_abertas == []
    assert validado.charges_pagas_ultimos_30_dias == []


def test_charge_paga_recente_aceita_valor_identificado_nulo():
    """Cobranças marcadas 'quitado' manualmente pelo staff (fora do fluxo
    automático do A2) podem não ter valor_identificado preenchido — ver
    docs/schemas/023_status_cobranca_a1.sql."""
    validado = StatusCobrancaContrato.model_validate(
        {
            "charges_abertas": [],
            "charges_pagas_ultimos_30_dias": [
                {
                    "charge_id": "c3",
                    "tipo": "aluguel",
                    "mes_referencia": "2026-08-01",
                    "valor_esperado": 1500.0,
                    "valor_identificado": None,
                    "data_pagamento": "2026-08-15",
                    "status": "quitado",
                }
            ],
        }
    )
    assert validado.charges_pagas_ultimos_30_dias[0].valor_identificado is None


def test_status_cobranca_contrato_rejeita_status_desconhecido():
    with pytest.raises(ValidationError):
        StatusCobrancaContrato.model_validate(
            {
                "charges_abertas": [
                    {
                        "charge_id": "c1",
                        "tipo": "aluguel",
                        "mes_referencia": "2026-09-01",
                        "valor_esperado": 1500.0,
                        "data_vencimento": "2026-09-10",
                        "dias_atraso": 0,
                        "status": "status_que_nao_existe",
                    }
                ],
                "charges_pagas_ultimos_30_dias": [],
            }
        )


def test_status_cobranca_contrato_rejeita_campo_extra():
    """model_config = ConfigDict(extra='forbid') — mesmo padrão de
    DadosInquilino: se a RPC mudar de formato no banco sem avisar aqui, isso
    deve quebrar explicitamente, não virar um campo estranho que o Claude
    tenta interpretar sozinho."""
    with pytest.raises(ValidationError):
        StatusCobrancaContrato.model_validate(
            {
                "charges_abertas": [],
                "charges_pagas_ultimos_30_dias": [],
                "campo_que_nao_deveria_existir": True,
            }
        )
```

- [ ] **Step 2: Rodar os testes e confirmar que falham (o schema ainda não existe)**

Run: `pytest tests/test_a1_status_cobranca.py -v`
Expected: FAIL com `ImportError: cannot import name 'StatusCobrancaContrato'`

- [ ] **Step 3: Implementar os schemas**

No final de `app/agents/a1_atendimento/schemas.py` (depois da classe `RegistroHistorico`, que termina na linha 106), adicionar:

```python


# --- Status de cobrança (Migration 023 — buscar_status_cobranca_inquilino) --
#
# TipoCobranca/StatusCharge duplicam de propósito os equivalentes em
# app/agents/a2_cobranca/schemas.py (mesmos valores, mesma origem: a check
# constraint de `charges` na Migration 001) — cada agente fica isolado do
# domínio do outro, mesmo espírito de CategoriaClausulaContrato acima não
# ser importado de lugar nenhum. Nunca importar deste módulo para o A2 nem
# o contrário.

TipoCobranca = Literal["aluguel", "agua"]
StatusCharge = Literal[
    "pendente", "aguardando_confirmacao", "confirmado", "divergente",
    "atrasado", "em_negociacao", "quitado",
]


class ChargeEmAberto(BaseModel):
    """Uma cobrança do contrato ainda não paga/confirmada — qualquer status
    diferente de 'confirmado'/'quitado'. Espelha um item de
    `charges_abertas` no retorno de `buscar_status_cobranca_inquilino`
    (ver docs/schemas/023_status_cobranca_a1.sql)."""

    model_config = ConfigDict(extra="forbid")

    charge_id: str
    tipo: TipoCobranca
    mes_referencia: str
    valor_esperado: float
    data_vencimento: str
    dias_atraso: int
    status: StatusCharge


class ChargePagaRecente(BaseModel):
    """Uma cobrança com pagamento identificado (`data_pagamento` != null)
    nos ÚLTIMOS 30 DIAS — a janela já vem filtrada pela própria RPC no
    banco, não é uma lista completa de pagamentos. Ver o aviso
    correspondente no SYSTEM_PROMPT de atendimento.py."""

    model_config = ConfigDict(extra="forbid")

    charge_id: str
    tipo: TipoCobranca
    mes_referencia: str
    valor_esperado: float
    valor_identificado: Optional[float] = None
    data_pagamento: str
    status: StatusCharge


class StatusCobrancaContrato(BaseModel):
    """Retorno esperado da RPC `buscar_status_cobranca_inquilino` (sem
    parâmetros — o contrato é resolvido internamente via
    agent_contract_id(), mesmo padrão de DadosInquilino acima)."""

    model_config = ConfigDict(extra="forbid")

    charges_abertas: list[ChargeEmAberto] = Field(default_factory=list)
    charges_pagas_ultimos_30_dias: list[ChargePagaRecente] = Field(default_factory=list)
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_a1_status_cobranca.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add app/agents/a1_atendimento/schemas.py tests/test_a1_status_cobranca.py
git commit -m "feat(a1): schemas Pydantic de status de cobranca (RPC 023)"
```

---

### Task 3: Wiring da tool no A1 (executor + tool schema + loop de tool-use)

**Files:**
- Modify: `app/agents/a1_atendimento/atendimento.py:65-67` (nova constante de tool)
- Modify: `app/agents/a1_atendimento/atendimento.py:47` (import do novo schema)
- Modify: `app/agents/a1_atendimento/atendimento.py:182-240` (`_tools_schema`)
- Modify: `app/agents/a1_atendimento/atendimento.py:280-292` (novo executor, ao lado de `_executar_consultar_historico`)
- Modify: `app/agents/a1_atendimento/atendimento.py:361-379` (despacho no loop de `responder_inquilino`)
- Test: `tests/test_a1_status_cobranca.py` (adiciona testes do executor, mesmo arquivo do Task 2)

**Interfaces:**
- Consumes: `StatusCobrancaContrato` de `app.agents.a1_atendimento.schemas` (Task 2); `obter_client_agente` de `app.orchestrator.agent_auth` (já importado).
- Produces: `TOOL_BUSCAR_STATUS_COBRANCA = "buscar_status_cobranca_inquilino"` (str), `_executar_buscar_status_cobranca(contract_id: str) -> dict` — Task 4 referencia esse nome de tool no `SYSTEM_PROMPT`.

- [ ] **Step 1: Escrever os testes do executor (falham primeiro)**

Adicionar ao final de `tests/test_a1_status_cobranca.py`:

```python


# --- _executar_buscar_status_cobranca (wrapper Python da RPC) -------------

from unittest.mock import MagicMock, patch  # noqa: E402

from app.agents.a1_atendimento import atendimento  # noqa: E402

CONTRACT_ID_FAKE = "11111111-1111-1111-1111-111111111111"


def _client_fake(retorno_rpc) -> MagicMock:
    client = MagicMock()
    resposta = MagicMock()
    resposta.data = retorno_rpc
    client.rpc.return_value.execute.return_value = resposta
    return client


def test_executar_buscar_status_cobranca_chama_rpc_sem_parametros():
    retorno = {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}
    client = _client_fake(retorno)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    client.rpc.assert_called_once_with("buscar_status_cobranca_inquilino", {})
    assert resultado == retorno


def test_executar_buscar_status_cobranca_devolve_dados_da_rpc():
    retorno = {
        "charges_abertas": [
            {
                "charge_id": "c1",
                "tipo": "aluguel",
                "mes_referencia": "2026-09-01",
                "valor_esperado": 1500.0,
                "data_vencimento": "2026-09-10",
                "dias_atraso": 3,
                "status": "atrasado",
            }
        ],
        "charges_pagas_ultimos_30_dias": [],
    }
    client = _client_fake(retorno)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    assert resultado["charges_abertas"][0]["status"] == "atrasado"


def test_executar_buscar_status_cobranca_com_retorno_none_vira_listas_vazias():
    """Se a RPC devolver null (ex: contrato sem nenhuma charge cadastrada
    ainda), o wrapper não deve quebrar tentando indexar um dict inexistente."""
    client = _client_fake(None)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    assert resultado == {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}


def test_executar_buscar_status_cobranca_com_shape_invalido_levanta_erro():
    """Formato inesperado da RPC (ex: mudou no banco sem avisar aqui) deve
    quebrar explicitamente na validação Pydantic — mesma doutrina de
    _executar_buscar_dados_inquilino."""
    from pydantic import ValidationError

    retorno_invalido = {
        "charges_abertas": [{"charge_id": "c1"}],  # faltam campos obrigatórios
        "charges_pagas_ultimos_30_dias": [],
    }
    client = _client_fake(retorno_invalido)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        with pytest.raises(ValidationError):
            atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)


def test_tools_schema_registra_buscar_status_cobranca():
    nomes = {t["name"] for t in atendimento._tools_schema()}
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA in nomes
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA == "buscar_status_cobranca_inquilino"
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `pytest tests/test_a1_status_cobranca.py -v`
Expected: FAIL com `AttributeError: module 'app.agents.a1_atendimento.atendimento' has no attribute '_executar_buscar_status_cobranca'`

- [ ] **Step 3: Import do schema novo**

Em `app/agents/a1_atendimento/atendimento.py:47`, trocar:

```python
from app.agents.a1_atendimento.schemas import DadosInquilino, RegistroHistorico
```

por:

```python
from app.agents.a1_atendimento.schemas import (
    DadosInquilino,
    RegistroHistorico,
    StatusCobrancaContrato,
)
```

- [ ] **Step 4: Nova constante de tool**

Em `app/agents/a1_atendimento/atendimento.py:65-67`, trocar:

```python
TOOL_BUSCAR_DADOS = "buscar_dados_inquilino"
TOOL_CONSULTAR_HISTORICO = "consultar_historico"
TOOL_ESCALAR_SEM_CLAUSULA = "escalar_sem_clausula"
```

por:

```python
TOOL_BUSCAR_DADOS = "buscar_dados_inquilino"
TOOL_CONSULTAR_HISTORICO = "consultar_historico"
TOOL_ESCALAR_SEM_CLAUSULA = "escalar_sem_clausula"
TOOL_BUSCAR_STATUS_COBRANCA = "buscar_status_cobranca_inquilino"
```

- [ ] **Step 5: Nova entrada em `_tools_schema()`**

Em `app/agents/a1_atendimento/atendimento.py`, dentro de `_tools_schema()` (linha 182), adicionar um novo dict à lista retornada — logo após o dict de `TOOL_CONSULTAR_HISTORICO` (que termina na linha 220) e antes do dict de `TOOL_ESCALAR_SEM_CLAUSULA`:

```python
        {
            "name": TOOL_BUSCAR_STATUS_COBRANCA,
            "description": (
                "Busca as cobranças (aluguel/água) do contrato desta conversa que ainda "
                "não estão pagas/confirmadas ('charges_abertas', com status e dias de "
                "atraso), e as cobranças com pagamento identificado nos ÚLTIMOS 30 DIAS "
                "('charges_pagas_ultimos_30_dias'). Chame quando o inquilino perguntar se "
                "tem alguma conta/cobrança em aberto, o status de um pagamento, ou se um "
                "pagamento recente já foi identificado. NÃO é histórico completo — "
                "pagamentos com mais de 30 dias não aparecem aqui."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
```

- [ ] **Step 6: Novo executor**

Em `app/agents/a1_atendimento/atendimento.py`, logo após `_executar_consultar_historico` (que termina na linha 291, antes de `def responder_inquilino`), adicionar:

```python


def _executar_buscar_status_cobranca(contract_id: str) -> dict:
    # Mesmo padrão de segurança de _executar_buscar_dados_inquilino: contract_id
    # só escolhe QUAL client/token usar — a RPC em si não recebe contract_id como
    # argumento, resolve isso internamente via agent_contract_id().
    client = obter_client_agente(contract_id)
    resposta = client.rpc(TOOL_BUSCAR_STATUS_COBRANCA, {}).execute()
    dados = resposta.data or {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}

    # Valida contra o schema esperado ANTES de repassar pro modelo — mesmo motivo
    # de _executar_buscar_dados_inquilino: se a RPC mudar de formato no banco sem
    # avisar aqui, isso deve quebrar aqui de forma explícita.
    StatusCobrancaContrato.model_validate(dados)

    return dados
```

- [ ] **Step 7: Despachar a nova tool no loop de `responder_inquilino`**

Em `app/agents/a1_atendimento/atendimento.py`, dentro do loop `for bloco in blocos_tool_use:` (linhas 362-374), trocar:

```python
                if bloco.name == TOOL_BUSCAR_DADOS:
                    resultado = _executar_buscar_dados_inquilino(contract_id)
                elif bloco.name == TOOL_CONSULTAR_HISTORICO:
                    resultado = _executar_consultar_historico(
                        contract_id,
                        bloco.input.get("limite", 10),
                        bloco.input.get("tipo", "todos"),
                    )
                else:
```

por:

```python
                if bloco.name == TOOL_BUSCAR_DADOS:
                    resultado = _executar_buscar_dados_inquilino(contract_id)
                elif bloco.name == TOOL_CONSULTAR_HISTORICO:
                    resultado = _executar_consultar_historico(
                        contract_id,
                        bloco.input.get("limite", 10),
                        bloco.input.get("tipo", "todos"),
                    )
                elif bloco.name == TOOL_BUSCAR_STATUS_COBRANCA:
                    resultado = _executar_buscar_status_cobranca(contract_id)
                else:
```

(O bloco `else: logger.warning(...)` que já existe continua exatamente igual, só ganha mais um `elif` acima dele.)

- [ ] **Step 8: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_a1_status_cobranca.py -v`
Expected: PASS (10 testes no total — 5 do Task 2 + 5 novos deste Step 1: 4 do executor + `test_tools_schema_registra_buscar_status_cobranca`)

- [ ] **Step 9: Rodar a suíte unitária inteira (regressão)**

Run: `pytest tests/ -m "not integration" -q`
Expected: PASS, sem nenhum teste existente quebrado

- [ ] **Step 10: Commit**

```bash
git add app/agents/a1_atendimento/atendimento.py tests/test_a1_status_cobranca.py
git commit -m "feat(a1): tool buscar_status_cobranca_inquilino no loop de tool-use"
```

---

### Task 4: SYSTEM_PROMPT — instruções de contas em aberto e janela de 30 dias

**Files:**
- Modify: `app/agents/a1_atendimento/atendimento.py:69-179` (`SYSTEM_PROMPT`)
- Test: `tests/test_a1_atendimento_prompt.py` (modificado)

**Interfaces:**
- Consumes: `atendimento.SYSTEM_PROMPT` (string), `TOOL_BUSCAR_STATUS_COBRANCA` (Task 3).
- Produces: nenhuma interface nova — só o texto do prompt.

- [ ] **Step 1: Escrever os testes de regressão do prompt (falham primeiro)**

Adicionar ao final de `tests/test_a1_atendimento_prompt.py`:

```python


def test_system_prompt_tem_secao_de_contas_em_aberto():
    assert "## CONTAS EM ABERTO" in atendimento.SYSTEM_PROMPT


def test_system_prompt_explica_os_status_de_cobranca_em_linguagem_simples():
    """O modelo não deve citar o valor cru do campo 'status' — precisa
    parafrasear. Este teste tranca que as explicações de cada status
    continuam no prompt (regressão)."""
    prompt = atendimento.SYSTEM_PROMPT.lower()
    for status_explicado in ("pendente", "atrasado", "aguardando_confirmacao", "divergente", "em_negociacao"):
        assert status_explicado in prompt


def test_system_prompt_limita_historico_de_pagamento_a_30_dias():
    """Regressão do requisito explícito do usuário: histórico de pagamento
    não é irrestrito — só cobranças com data de pagamento identificada nos
    últimos 30 dias, e o modelo não pode inventar nada fora dessa janela."""
    prompt = atendimento.SYSTEM_PROMPT
    assert "30 dias" in prompt
    assert "nunca" in prompt.lower() and "invente" in prompt.lower()


def test_system_prompt_menciona_tool_buscar_status_cobranca():
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA in atendimento.SYSTEM_PROMPT
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `pytest tests/test_a1_atendimento_prompt.py -v`
Expected: FAIL (seção `## CONTAS EM ABERTO` ainda não existe no prompt)

- [ ] **Step 3: Adicionar a seção ao `SYSTEM_PROMPT`**

Em `app/agents/a1_atendimento/atendimento.py`, dentro da string `SYSTEM_PROMPT`, logo após a seção `## ONDE PAGAR` (que termina em "...chame 'escalar_sem_clausula' se a pergunta específica não puder ser respondida por falta desse dado)." — linha 162) e antes de `## AVISO INFORMAL DE PAGAMENTO JÁ FEITO` (linha 164), inserir:

```

## CONTAS EM ABERTO E HISTÓRICO DE PAGAMENTO (últimos 30 dias)
Se o inquilino perguntar se existe alguma conta/cobrança em aberto, pendente ou atrasada,
ou sobre o status de um pagamento recente (ex: "tem alguma conta em aberto?", "já caiu meu
pagamento?", "paguei a água, já confirmou?"), chame a tool 'buscar_status_cobranca_inquilino'.

'charges_abertas' são cobranças que AINDA precisam de atenção. Explique o status de cada
uma em linguagem simples e curta, NUNCA cite o valor cru do campo 'status':
- pendente: ainda dentro do prazo, aguardando pagamento.
- atrasado: passou da data de vencimento sem pagamento identificado.
- aguardando_confirmacao: o comprovante já foi recebido e está sendo conferido pela equipe.
- divergente: o comprovante enviado teve alguma divergência (valor ou dado) — a equipe vai
  entrar em contato.
- em_negociacao: está em negociação com a equipe, fora do fluxo automático.
Se 'charges_abertas' vier vazia, diga claramente que não há nenhuma conta em aberto no
momento.

'charges_pagas_ultimos_30_dias' cobre APENAS cobranças com pagamento identificado nos
ÚLTIMOS 30 DIAS — NÃO é o histórico completo de pagamentos. Se o inquilino pedir um
histórico mais antigo que isso, diga que você só tem visibilidade dos últimos 30 dias e que
vai verificar com a equipe (mesmo espírito da seção 'PEDIDOS ADMINISTRATIVOS SIMPLES' abaixo
— não prometa prazo, e não chame 'escalar_sem_clausula' para isso, já que não é uma lacuna
de cláusula, é limitação de dado). NUNCA invente se uma cobrança fora dessa janela de 30
dias foi paga ou não.
```

- [ ] **Step 4: Adicionar a nova capacidade ao `## ESCOPO`**

Em `app/agents/a1_atendimento/atendimento.py`, dentro de `SYSTEM_PROMPT`, na seção `## ESCOPO` (o cabeçalho `## ESCOPO` está na linha 71, o parágrafo a trocar é linhas 72-75), trocar:

```python
Você responde APENAS perguntas diretas sobre o contrato de locação do inquilino desta
conversa — valor do aluguel, data de vencimento, endereço do imóvel, vigência do contrato,
forma de reajuste, garantias (caução ou fiador), cláusulas específicas, e histórico de
atendimentos/tickets já abertos.
```

por:

```python
Você responde APENAS perguntas diretas sobre o contrato de locação do inquilino desta
conversa — valor do aluguel, data de vencimento, endereço do imóvel, vigência do contrato,
forma de reajuste, garantias (caução ou fiador), cláusulas específicas, se há alguma conta
em aberto e o status de pagamentos recentes (últimos 30 dias), e histórico de atendimentos/
tickets já abertos.
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_a1_atendimento_prompt.py tests/test_a1_status_cobranca.py -v`
Expected: PASS

- [ ] **Step 6: Rodar a suíte unitária inteira (regressão)**

Run: `pytest tests/ -m "not integration" -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/agents/a1_atendimento/atendimento.py tests/test_a1_atendimento_prompt.py
git commit -m "feat(a1): SYSTEM_PROMPT explica contas em aberto e janela de 30 dias"
```

---

### Task 5: Classificador — roteamento explícito de "conta em aberto" para A1

**Files:**
- Modify: `app/orchestrator/classificador.py:76-94` (`SYSTEM_PROMPT`)
- Test: `tests/test_classificador_intencao.py` (modificado)

**Interfaces:**
- Consumes: nenhuma nova.
- Produces: nenhuma interface nova — só o texto do prompt do classificador.

- [ ] **Step 1: Escrever o teste de regressão (falha primeiro)**

Adicionar ao final de `tests/test_classificador_intencao.py`:

```python


def test_system_prompt_orienta_conta_em_aberto_para_a1():
    """Regressão do gap de 'existe conta em aberto pro meu apartamento?' —
    sem exemplo explícito, essa pergunta corria risco de ser roteada errado
    (ex: para A5, por soar como assunto financeiro) em vez de A1, que agora
    tem a tool buscar_status_cobranca_inquilino (Migration 023) pra
    responder isso com dado real."""
    prompt = clf.SYSTEM_PROMPT.lower()
    assert "conta" in prompt and "aberto" in prompt
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest tests/test_classificador_intencao.py -v`
Expected: FAIL em `test_system_prompt_orienta_conta_em_aberto_para_a1`

- [ ] **Step 3: Atualizar o bullet do A1 no `SYSTEM_PROMPT` do classificador**

Em `app/orchestrator/classificador.py:78`, trocar:

```python
    "onde/como pagar (chave Pix, dados bancários), perguntas HIPOTÉTICAS sobre "
```

por:

```python
    "onde/como pagar (chave Pix, dados bancários), se existe alguma conta ou cobrança em "
    "aberto e o status de pagamentos recentes (últimos 30 dias), perguntas HIPOTÉTICAS sobre "
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_classificador_intencao.py -v`
Expected: PASS (todos os testes do arquivo, incluindo os pré-existentes)

- [ ] **Step 5: Rodar a suíte unitária inteira (regressão)**

Run: `pytest tests/ -m "not integration" -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/orchestrator/classificador.py tests/test_classificador_intencao.py
git commit -m "feat(orchestrator): classificador roteia 'conta em aberto' para A1"
```

---

### Task 6: Testes de integração ponta a ponta

**Files:**
- Create: `tests/integration/test_a1_status_cobranca_integration.py`

**Interfaces:**
- Consumes: fixtures `contrato_pf_padrao`, `contrato_pj_caucao`, `contrato_para_escalonamento`, `enviar_mensagem_simulada`, `agente_client_factory`, `service_role_client` (já existentes em `tests/integration/conftest.py` e `tests/integration/fixtures/contratos.py`).
- Produces: nenhuma interface nova — só os testes. A classe `TestGarantiaDeFiltragemNaRpc` chama `buscar_status_cobranca_inquilino` direto via `agente_client_factory(contract_id).rpc(...)`, sem passar pelo Claude — trava o contrato da RPC (Task 1) independente da fraseação do modelo, e sem custo de Anthropic.

Nota: `contrato_pf_padrao` já nasce com uma charge `tipo=aluguel status=pendente` (ver `tests/integration/fixtures/contratos.py:128-137`). `contrato_pj_caucao` já nasce com uma charge `tipo=agua status=confirmado data_pagamento=hoje` (linhas 167-178). Nenhuma fixture nova precisa ser criada — reaproveita as existentes.

- [ ] **Step 1: Escrever os testes**

Criar `tests/integration/test_a1_status_cobranca_integration.py`:

```python
"""A1 (Atendimento) respondendo sobre contas em aberto e histórico de
pagamento recente — ponta a ponta contra o Supabase de teste real e a API
real da Anthropic (mesmo padrão de test_a1_atendimento_integration.py).
"""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


class TestA1RespondeStatusCobranca:
    def test_avisa_cobranca_em_aberto(self, contrato_pf_padrao, enviar_mensagem_simulada):
        """contrato_pf_padrao já nasce com uma charge tipo=aluguel
        status=pendente (fixtures/contratos.py) — o A1 deve mencionar que
        existe uma conta em aberto, sem inventar que está tudo pago."""
        telefone = contrato_pf_padrao["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Tem alguma conta em aberto no meu apartamento?",
        )

        resposta = resultado["resposta"].lower()
        assert "aluguel" in resposta
        assert not any(
            frase in resposta
            for frase in ("nenhuma conta em aberto", "tudo em dia", "sem pendências", "sem pendencias")
        )

    def test_sem_charges_diz_que_nao_ha_conta_em_aberto(
        self, contrato_para_escalonamento, enviar_mensagem_simulada
    ):
        """contrato_para_escalonamento não tem nenhuma charge cadastrada
        (fixtures/contratos.py) — charges_abertas vem vazia da RPC, o A1
        precisa dizer isso com clareza, não inventar uma pendência."""
        telefone = contrato_para_escalonamento["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Tem alguma conta em aberto no meu apartamento?",
        )

        resposta = resultado["resposta"].lower()
        assert any(
            frase in resposta
            for frase in ("nenhuma conta em aberto", "não há conta", "nao ha conta", "tudo em dia", "sem pendências", "sem pendencias", "não tem nenhuma")
        )

    def test_confirma_pagamento_recente_dentro_de_30_dias(
        self, contrato_pj_caucao, enviar_mensagem_simulada
    ):
        """contrato_pj_caucao já nasce com uma charge tipo=agua,
        status=confirmado, data_pagamento=hoje (fixtures/contratos.py) —
        dentro da janela de 30 dias."""
        telefone = contrato_pj_caucao["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="A conta de água que eu paguei já foi identificada?",
        )

        resposta = resultado["resposta"].lower()
        assert "água" in resposta or "agua" in resposta

    def test_nao_afirma_pagamento_fora_da_janela_de_30_dias(
        self, contrato_pj_caucao, enviar_mensagem_simulada, service_role_client
    ):
        """Regressão do requisito explícito do usuário: pagamento
        identificado há mais de 30 dias não deve ser tratado como recente.
        Move a data_pagamento da charge da fixture para 45 dias atrás."""
        contract_id = contrato_pj_caucao["contract_id"]
        telefone = contrato_pj_caucao["telefone"]
        data_antiga = (date.today() - timedelta(days=45)).isoformat()

        service_role_client.table("charges").update(
            {"data_pagamento": data_antiga}
        ).eq("contract_id", contract_id).execute()

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Meu pagamento de água recente já foi confirmado?",
        )

        resposta = resultado["resposta"].lower()
        assert "30 dias" in resposta


class TestGarantiaDeFiltragemNaRpc:
    """Diferente da classe acima, estes testes chamam a RPC direto (sem
    passar pelo Claude) — mais barato (zero custo de Anthropic, ver nota de
    custo em tests/integration/README.md) e mais preciso pra travar o
    CONTRATO da RPC em si, não a fraseação do modelo. Prova as duas metades
    da mesma garantia (ver docs/schemas/023_status_cobranca_a1.sql):
    (1) charges_abertas nunca tem condição de data no WHERE (nem
    data_vencimento nem data_pagamento) — uma conta em aberto aparece
    sempre, mesmo com vencimento muito antigo ou data_pagamento nula;
    (2) charges_pagas_ultimos_30_dias filtra data_pagamento NA QUERY — um
    pagamento fora da janela de 30 dias nunca sai do Postgres, não é
    escondido depois em Python nem deixado a critério do modelo."""

    def test_conta_em_aberto_aparece_mesmo_com_vencimento_muito_antigo(
        self, contrato_pf_padrao, agente_client_factory, service_role_client
    ):
        contract_id = contrato_pf_padrao["contract_id"]
        vencimento_antigo = date.today() - timedelta(days=200)

        service_role_client.table("charges").insert(
            {
                "contract_id": contract_id,
                "tipo": "agua",
                "mes_referencia": vencimento_antigo.replace(day=1).isoformat(),
                "valor_esperado": 90.0,
                "data_vencimento": vencimento_antigo.isoformat(),
                "dias_atraso": 200,
                "status": "atrasado",
            }
        ).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        tipos_em_aberto = {c["tipo"] for c in resultado["charges_abertas"]}
        # A charge de água inserida agora (200 dias vencida) E a charge de
        # aluguel que já vem da fixture (contrato_pf_padrao) precisam
        # continuar as duas em charges_abertas.
        assert "agua" in tipos_em_aberto
        assert "aluguel" in tipos_em_aberto

        agua_aberta = next(c for c in resultado["charges_abertas"] if c["tipo"] == "agua")
        assert agua_aberta["dias_atraso"] == 200
        assert agua_aberta["status"] == "atrasado"

        # Nenhuma das duas tem data_pagamento preenchida — nenhuma pode
        # aparecer no histórico de pagamento, e a lista não pode ter
        # travado/quebrado por causa da data de vencimento antiga.
        assert resultado["charges_pagas_ultimos_30_dias"] == []

    def test_conta_em_aberto_com_status_divergente_nao_e_perdida(
        self, contrato_pf_padrao, service_role_client, agente_client_factory
    ):
        """status='divergente' nunca ganha data_pagamento (ver
        app/agents/a2_cobranca/comprovante.py::marcar_valor_divergente) —
        confirma que mesmo sem NENHUMA data de pagamento (nem antiga nem
        recente), a charge continua aparecendo em charges_abertas."""
        contract_id = contrato_pf_padrao["contract_id"]

        charge_id = (
            service_role_client.table("charges")
            .select("id")
            .eq("contract_id", contract_id)
            .single()
            .execute()
            .data["id"]
        )
        service_role_client.table("charges").update({"status": "divergente"}).eq(
            "id", charge_id
        ).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        status_abertos = {c["charge_id"]: c["status"] for c in resultado["charges_abertas"]}
        assert status_abertos.get(charge_id) == "divergente"
        assert resultado["charges_pagas_ultimos_30_dias"] == []

    def test_pagamento_antigo_nunca_aparece_no_retorno_da_rpc(
        self, contrato_pj_caucao, service_role_client, agente_client_factory
    ):
        """Lado oposto da garantia: a exclusão de charges_pagas_ultimos_30_dias
        acontece NA QUERY (WHERE data_pagamento >= current_date - 30), não
        depois em Python nem por o modelo "escolher não mencionar" — a linha
        nem chega a sair do Postgres. contrato_pj_caucao já nasce com uma
        charge tipo=agua, status=confirmado, data_pagamento=hoje
        (fixtures/contratos.py); move para 45 dias atrás e confirma que ela
        desaparece do retorno da RPC por completo."""
        contract_id = contrato_pj_caucao["contract_id"]
        data_antiga = (date.today() - timedelta(days=45)).isoformat()

        service_role_client.table("charges").update(
            {"data_pagamento": data_antiga}
        ).eq("contract_id", contract_id).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        assert resultado["charges_pagas_ultimos_30_dias"] == []
        # Também não pode "vazar" para charges_abertas: confirmado/quitado é
        # excluído de lá independente da idade do pagamento (ver Task 1).
        assert resultado["charges_abertas"] == []
```

- [ ] **Step 2: Rodar os testes (requer `.env.test` configurado — ver `tests/integration/README.md`)**

Run: `pytest -m integration tests/integration/test_a1_status_cobranca_integration.py -v`
Expected: PASS (7 testes: 4 na classe `TestA1RespondeStatusCobranca` via Claude real + 3 na classe `TestGarantiaDeFiltragemNaRpc`, direto na RPC, sem custo de Anthropic). Sem `.env.test` preenchido, a suíte inteira é pulada (`SKIPPED`), não falha — comportamento padrão documentado em `tests/integration/README.md`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_a1_status_cobranca_integration.py
git commit -m "test(a1): integração ponta a ponta de status de cobranca"
```

---

## Self-Review (já aplicado ao escrever este plano)

1. **Cobertura da spec:** "responder se existe contas em aberto e o status de cada uma" → Tasks 1, 2, 3, 4 (RPC `charges_abertas` + tradução de status). "histórico de contas pagas... apenas com data de pagamento identificado nos últimos 30 dias" → Tasks 1 (filtro SQL `current_date - interval '30 days'`), 4 (instrução explícita no prompt), 6 (teste de regressão do corte de 30 dias). Roteamento correto até o A1 → Task 5. **Garantia explícita pedida na revisão desta conversa** — "as em aberto passam sempre mesmo que a data seja nula ou antes de 30 dias" — já é estrutural: a query de `charges_abertas` (Task 1) não tem NENHUMA condição de data no `WHERE`, só `status`; travada por dois testes diretos na RPC em `TestGarantiaDeFiltragemNaRpc` (Task 6) com vencimento de 200 dias atrás e com status `divergente` (sem `data_pagamento` nenhuma).
2. **Placeholder scan:** nenhum "TBD"/"implementar depois" — todo Step tem código completo.
3. **Consistência de tipos:** `TOOL_BUSCAR_STATUS_COBRANCA` (Task 3) é o mesmo nome usado no `client.rpc(...)` (Task 3, Step 6), no teste (`client.rpc.assert_called_once_with("buscar_status_cobranca_inquilino", {})`) e no nome da função SQL (Task 1). `StatusCobrancaContrato`/`ChargeEmAberto`/`ChargePagaRecente` (Task 2) são os únicos nomes usados em Task 3 e nos testes — sem divergência.

---

**Plan complete and saved to `docs/superpowers/plans/2026-09-04-a1-status-cobranca.md`. Duas opções de execução:**

**1. Subagent-Driven (recomendado)** - dispatch de um subagente por task, revisão entre tasks, iteração rápida

**2. Inline Execution** - execução das tasks nesta sessão via executing-plans, execução em lote com checkpoints

**Qual abordagem?**
