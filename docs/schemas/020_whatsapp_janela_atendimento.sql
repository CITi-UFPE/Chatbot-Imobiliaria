-- ============================================================
-- MIGRATION 020 — Janela de atendimento do WhatsApp por contrato
-- ============================================================
-- Depende das Migrations 001 e 002.
--
-- Expõe somente o instante da última mensagem recebida do inquilino no
-- contrato presente no JWT do papel agente_ia. A função não aceita
-- contract_id como parâmetro e não amplia nenhuma policy de RLS.
-- ============================================================

begin;

create or replace function public.agent_get_last_tenant_message_at()
returns timestamptz
language sql
security definer
stable
set search_path = ''
as $$
  select max(cl."timestamp")
  from public.conversation_logs cl
  where cl.contract_id = public.agent_contract_id()
    and cl.remetente = 'inquilino';
$$;

revoke all on function public.agent_get_last_tenant_message_at() from public;
revoke all on function public.agent_get_last_tenant_message_at() from anon;
revoke all on function public.agent_get_last_tenant_message_at() from authenticated;
revoke all on function public.agent_get_last_tenant_message_at() from cron_batch;
grant execute on function public.agent_get_last_tenant_message_at() to agente_ia;

comment on function public.agent_get_last_tenant_message_at() is
  'Retorna a última mensagem do inquilino no contrato do JWT atual; null sem histórico.';

commit;

-- ============================================================
-- FIM DA MIGRATION 020
-- ============================================================
