-- ============================================================
-- MIGRATION 028 — multa e juros opcionais por cobrança (charges.aplicar_encargos)
-- ============================================================
-- Depende das Migrations 001 (charges), 008/025 (cron_listar_charges_ativas) e
-- 023 (buscar_status_cobranca_inquilino).
--
-- Pedido do cliente (30/10 e 11/11/2026): ao lançar uma conta de água, a equipe
-- escolhe se aquela conta leva multa e juros contratuais. Até hoje a água fica
-- sem encargos por uma trava fixa no código (TIPOS_SEM_ENCARGOS).
--
--   charges.aplicar_encargos boolean NULL
--     true  -> a cobrança leva multa e juros;
--     false -> o valor fica como foi lançado;
--     NULL  -> sem escolha registrada: vale o padrão do tipo (água sem
--              encargos, aluguel com), igual ao comportamento de antes.
--   Sem default e sem backfill de propósito: aluguéis e águas já lançados, e
--   qualquer insert que não conheça a coluna, seguem exatamente como hoje.
--
--   As duas RPCs que o backend usa para ler charges passam a devolver a coluna:
--   cron_listar_charges_ativas (cron do A2) e buscar_status_cobranca_inquilino
--   (tool do A1). Elas devolvem "returns table"/jsonb de formato fixo.
--
-- ORDEM DE DEPLOY: subir o backend ANTES desta migration. Os modelos
-- ChargeAtiva (A2) e ChargeEmAberto (A1) têm extra="forbid"; a versão nova já
-- aceita a coluna ausente, a antiga quebraria ao receber a coluna nova. O
-- frontend que seleciona aplicar_encargos só sobe DEPOIS desta migration.
-- ============================================================

begin;

alter table charges add column if not exists aplicar_encargos boolean;

comment on column charges.aplicar_encargos is
  'Escolha da equipe: true = aplica multa/juros, false = não aplica, NULL = padrão do tipo (água sem encargos, aluguel com). Migration 028.';

-- ------------------------------------------------------------
-- cron_listar_charges_ativas — o "returns table" muda, então não basta
-- "create or replace": é preciso dropar e recriar. Corpo e filtro idênticos
-- aos da Migration 025 (seção 25.3), só com a coluna nova no fim. O grant do
-- papel cron_batch (Migration 008) é refeito logo abaixo.
-- ------------------------------------------------------------
drop function if exists cron_listar_charges_ativas();

create function cron_listar_charges_ativas()
returns table (
  contract_id       uuid,
  charge_id         uuid,
  tipo              text,
  mes_referencia    date,
  valor_esperado    numeric,
  data_vencimento   date,
  data_pagamento    date,
  dias_atraso       integer,
  status            text,
  mensagem_estagio  text,
  aplicar_encargos  boolean
)
language sql
security definer
stable
as $$
  select
    c.id, ch.id, ch.tipo, ch.mes_referencia, ch.valor_esperado,
    ch.data_vencimento, ch.data_pagamento, ch.dias_atraso, ch.status, ch.mensagem_estagio,
    ch.aplicar_encargos
  from charges ch
  join contracts c on c.id = ch.contract_id
  where c.status = 'ativo'
    and ch.status in ('pendente', 'atrasado', 'divergente');
$$;

grant execute on function cron_listar_charges_ativas() to cron_batch;

-- ------------------------------------------------------------
-- buscar_status_cobranca_inquilino — mesma função da Migration 023, com
-- 'aplicar_encargos' em cada item de charges_abertas (o A1 decide se calcula
-- valor atualizado). Assinatura igual -> "create or replace" mantém o grant.
-- ------------------------------------------------------------
create or replace function public.buscar_status_cobranca_inquilino()
returns jsonb
language plpgsql
security definer
stable
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
    -- dias_atraso armazenado pode ser negativo para charges ainda não vencidas
    -- (ver app/agents/a2_cobranca/cobranca.py) — nunca deve chegar assim ao A1.
    'dias_atraso', greatest(ch.dias_atraso, 0),
    'status', ch.status,
    'aplicar_encargos', ch.aplicar_encargos
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
    and ch.status in ('confirmado', 'quitado')
    and ch.data_pagamento is not null
    and ch.data_pagamento >= (current_date - interval '30 days');

  return jsonb_build_object(
    'charges_abertas', v_abertas,
    'charges_pagas_ultimos_30_dias', v_pagas_recentes
  );
end;
$$;

commit;

-- ============================================================
-- FIM DA MIGRATION 028
-- ============================================================
