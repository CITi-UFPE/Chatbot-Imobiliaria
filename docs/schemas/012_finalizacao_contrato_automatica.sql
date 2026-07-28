-- ============================================================
-- MIGRATION 012 — Finalização automática de contrato no término (A4)
-- ============================================================
-- Depende das Migrations 001 e 010 já terem rodado (contracts,
-- agent_contract_id()).
--
-- Contexto: o Fluxo A (renovação, alerta D-60) virou um painel só de aviso,
-- sem nenhuma decisão da gestora registrada em contract_alerts. Todo
-- contrato ativo, ao chegar em data_termino, é desativado automaticamente
-- — não existe mais um "encerrar" opcional: se foi renovado, o contrato
-- novo já existe separado (criado no fluxo de leitura por IA) e este aqui
-- só está encerrando o ciclo que terminou; se não foi renovado, também
-- precisa terminar.
--
-- Diferente da primeira versão desta migration, NÃO existe aqui uma função
-- de listagem em lote nova. cron_listar_contratos_ativos() (Migration 010)
-- já devolve data_termino para todo contrato ativo, e o orquestrador do A4
-- (app/agents/a4_gestao_contratual/orquestracao.py) já itera essa lista
-- inteira uma vez por dia para os Fluxos A e B — bastava checar
-- contrato.data_termino == hoje dentro desse mesmo loop, sem duplicar uma
-- segunda leitura cross-contrato só pra isso. A única peça que faltava de
-- verdade era a ESCRITA: desativar precisa do token escopado por contrato
-- (agent_contract_id()), que nenhuma função existente fazia.
--
-- Continua rodando só no dia exato de data_termino (nunca antes) pelo mesmo
-- motivo de sempre: desativar cedo quebra contracts_telefone_ativo_uidx
-- (Migration 001) e as listagens em lote (cron_listar_contratos_ativos /
-- cron_listar_charges_ativas), que dependem de status='ativo' até o fim
-- real do contrato.
-- ============================================================

-- Desativa o contrato da chamada atual (agent_contract_id(), nunca um
-- parâmetro solto — mesmo racional de agent_aplicar_reajuste, Migration
-- 010). O "where status = 'ativo'" é o próprio guard de idempotência: se
-- o job chamar essa função duas vezes pro mesmo contrato (retry, deploy),
-- a segunda chamada não encontra linha pra atualizar e volta null — sem
-- precisar de uma coluna de controle separada.
create or replace function agent_finalizar_contrato()
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  update contracts
  set status = 'inativo',
      updated_at = now()
  where id = agent_contract_id()
    and status = 'ativo'
  returning id into v_id;

  return v_id;
end;
$$;

grant execute on function agent_finalizar_contrato() to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 012
-- ============================================================