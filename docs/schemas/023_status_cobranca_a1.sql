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
    and ch.status in ('confirmado', 'quitado')
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
