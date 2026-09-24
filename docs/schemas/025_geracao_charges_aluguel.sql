-- ============================================================
-- MIGRATION 025 — Geração automática das charges de aluguel (A2)
-- ============================================================
-- Problema: nenhuma migration nem código de app inseria charge de aluguel.
-- A constraint charges_unico_por_mes (Migration 001) já dizia "evita
-- cobrança duplicada se o job diário rodar duas vezes", mas o job que
-- gera nunca foi escrito — as charges existentes vieram da tela de Água
-- (tipo='agua') ou de scripts de seed/teste. Sem charge, o cron de
-- cobrança (cron_listar_charges_ativas, Migration 008) não tem o que
-- avaliar, e a virada de mês nunca produz as cobranças novas.
--
-- Mesma doutrina da Migration 008: cron_batch só LÊ em lote (quem precisa
-- de charge hoje); a ESCRITA vai contrato por contrato com o JWT do
-- agente_ia, escopada por agent_contract_id() — a função de insert nem
-- recebe contract_id como parâmetro.
--
-- Função nova de listagem em vez de alterar cron_listar_contratos_ativos
-- (Migration 016): aquela é usada pelo A4, e mudar o retorno exige DROP +
-- re-GRANT — risco desnecessário pra um consumidor que não precisa destes
-- campos.
--
-- Regra de datas (janela, dia 31, 'anterior', vigência) fica em Python
-- (app/agents/a2_cobranca/geracao.py), testável sem banco. O SQL só
-- garante isolamento, valor vindo do contrato e idempotência.
-- ============================================================

begin;

-- ------------------------------------------------------------
-- 25.1 — Listagem em lote (cron_batch): só os campos de calendário.
-- Sem dado pessoal e sem valor — o valor é lido na hora do insert.
-- ------------------------------------------------------------
create or replace function public.cron_listar_contratos_para_faturamento()
returns table (
  id                        uuid,
  dia_vencimento            integer,
  vencimento_mes_referencia text,
  data_inicio               date,
  data_termino              date,
  prazo_indeterminado       boolean
)
language sql
security definer
stable
set search_path = ''
as $$
  select c.id, c.dia_vencimento, c.vencimento_mes_referencia,
         c.data_inicio, c.data_termino, c.prazo_indeterminado
  from public.contracts c
  where c.status = 'ativo';
$$;

revoke all on function public.cron_listar_contratos_para_faturamento() from public;
revoke all on function public.cron_listar_contratos_para_faturamento() from anon;
revoke all on function public.cron_listar_contratos_para_faturamento() from authenticated;
grant execute on function public.cron_listar_contratos_para_faturamento() to cron_batch;

comment on function public.cron_listar_contratos_para_faturamento() is
  'Contratos ativos com os campos de calendário que o A2 usa para decidir qual charge de aluguel gerar hoje. Só leitura, cross-contrato, papel cron_batch (Migration 025).';

-- ------------------------------------------------------------
-- 25.2 — Insert escopado (agente_ia). valor_esperado vem de
-- contracts.valor_aluguel no momento da geração; status/dias_atraso/
-- mensagem_estagio ficam nos defaults da tabela. on conflict do nothing
-- na constraint de unicidade = rodar 2x no dia (ou charge já lançada à
-- mão pro mês) não duplica nem sobrescreve. Retorna null nesse caso.
-- ------------------------------------------------------------
create or replace function public.agent_gerar_charge_aluguel(
  p_mes_referencia  date,
  p_data_vencimento date
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_contract_id uuid := public.agent_contract_id();
  v_id uuid;
begin
  if v_contract_id is null then
    raise exception 'agent_gerar_charge_aluguel: token sem contract_id';
  end if;

  if p_mes_referencia <> date_trunc('month', p_mes_referencia)::date then
    raise exception 'agent_gerar_charge_aluguel: p_mes_referencia deve ser o dia 1 do mês (recebido %)', p_mes_referencia;
  end if;

  insert into public.charges (contract_id, tipo, mes_referencia, valor_esperado, data_vencimento)
  select c.id, 'aluguel', p_mes_referencia, c.valor_aluguel, p_data_vencimento
  from public.contracts c
  where c.id = v_contract_id
    and c.status = 'ativo'
  on conflict on constraint charges_unico_por_mes do nothing
  returning id into v_id;

  return v_id;
end;
$$;

revoke all on function public.agent_gerar_charge_aluguel(date, date) from public;
revoke all on function public.agent_gerar_charge_aluguel(date, date) from anon;
revoke all on function public.agent_gerar_charge_aluguel(date, date) from authenticated;
revoke all on function public.agent_gerar_charge_aluguel(date, date) from cron_batch;
grant execute on function public.agent_gerar_charge_aluguel(date, date) to agente_ia;

comment on function public.agent_gerar_charge_aluguel(date, date) is
  'Cria a charge de aluguel do mês para o contrato do token (agent_contract_id()). Idempotente via charges_unico_por_mes: retorna null se já existia. Migration 025.';

-- ------------------------------------------------------------
-- 25.3 — cron_listar_charges_ativas passa a excluir TODOS os status
-- pausados, não só 'quitado'. Antes, toda charge 'confirmado' (estado
-- final do fluxo do bot — 'quitado' só vem de negociação) voltava na
-- listagem TODO dia pra sempre e era descartada em Python
-- (cobranca.py:STATUS_PAUSADOS). dias_atraso não mudava (early return),
-- mas o custo de leitura/transferência crescia com o histórico — e com a
-- geração automática, cresce 1 charge por contrato por mês.
-- Mesma assinatura de retorno → create or replace basta (grant mantido).
-- STATUS_PAUSADOS em Python continua como defesa.
-- ------------------------------------------------------------
create or replace function cron_listar_charges_ativas()
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
  mensagem_estagio  text
)
language sql
security definer
stable
as $$
  select
    c.id, ch.id, ch.tipo, ch.mes_referencia, ch.valor_esperado,
    ch.data_vencimento, ch.data_pagamento, ch.dias_atraso, ch.status, ch.mensagem_estagio
  from charges ch
  join contracts c on c.id = ch.contract_id
  where c.status = 'ativo'
    and ch.status in ('pendente', 'atrasado', 'divergente');
$$;

-- Índice parcial: a varredura diária só toca as charges em aberto, que
-- ficam poucas mesmo com anos de histórico 'confirmado'/'quitado'.
create index if not exists charges_em_aberto_idx
  on charges (contract_id)
  where status in ('pendente', 'atrasado', 'divergente');

commit;

-- ============================================================
-- FIM DA MIGRATION 025
-- ============================================================
