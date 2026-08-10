-- ============================================================
-- MIGRATION 016 — Tipo de renovação (seleção manual) + pendência
-- de decisão de renovação (Projeto Domingos Monteiro)
-- ============================================================
-- Contexto: como o contrato se renova ao final do prazo NÃO é mais
-- inferido pela IA na extração — é escolhido manualmente pela gestora na
-- tela de conferência (Passo 3 do wizard de upload, ContratosSection.tsx),
-- porque a leitura de cláusulas de renovação por IA não tinha confiabilidade
-- suficiente pra decidir sozinha o que acontece com o contrato no
-- vencimento.
--
-- tipo_renovacao decide o que o cron do A4
-- (app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato)
-- faz quando o contrato chega em data_termino:
--   - novo_contrato (default): comportamento já existente
--     (agent_finalizar_contrato, Migration 012) — desativa normalmente,
--     sem pendência. Cobre também o caso de não haver continuidade.
--   - requer_aditivo / automatica / nao_identificado: contrato
--     "acionável" — se ninguém decidiu a renovação até data_termino,
--     desativa E marca pendente_decisao_renovacao=true, pra o card
--     continuar visível no dashboard (RenovacaoSection.tsx) até a gestora
--     resolver.
--   - indeterminado_por_lei: nunca desativa por esta via — vira
--     prazo_indeterminado=true automaticamente (mesma coluna da
--     Migration 013), pois a prorrogação decorre de lei (art. 46 §1º da
--     Lei 8.245/91), não de decisão humana.
--
-- A resolução da pendência (nova data de vencimento ou prazo indefinido,
-- ou confirmação de encerramento) é feita por escrita DIRETA em contracts
-- a partir do dashboard, com a sessão da própria gestora — mesmo padrão já
-- usado pelos botões "Desativar/Reativar Contrato" em ContratosSection.tsx
-- (RLS staff_full_access), não por RPC. Por isso esta migration só define
-- RPCs para o lado do cron (papel agente_ia, escopado por
-- agent_contract_id() — mesmo padrão de agent_finalizar_contrato /
-- agent_aplicar_reajuste já existentes).
-- ============================================================

alter table contracts
  add column if not exists tipo_renovacao text not null default 'novo_contrato'
    check (tipo_renovacao in (
      'novo_contrato', 'requer_aditivo', 'automatica',
      'indeterminado_por_lei', 'nao_identificado'
    ));

comment on column contracts.tipo_renovacao is
  'Como o contrato se renova ao final do prazo, escolhido manualmente pela gestora na tela de conferência (não inferido pela IA). Decide o comportamento do cron do A4 no vencimento — ver app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato e este arquivo.';

alter table contracts
  add column if not exists pendente_decisao_renovacao boolean not null default false;

alter table contracts
  add constraint pendente_so_quando_inativo
  check (not pendente_decisao_renovacao or status = 'inativo');

comment on column contracts.pendente_decisao_renovacao is
  'true = contrato desativado por falta de decisão de renovação até data_termino (tipo_renovacao requer_aditivo/automatica/nao_identificado). RenovacaoSection.tsx mantém o card visível (badge vermelho) até a gestora resolver — reativando com nova data/prazo indefinido, ou confirmando o encerramento.';

-- cron_listar_contratos_ativos (Migration 010, ajustada nas 013 e 014)
-- precisa devolver tipo_renovacao pro dispatcher decidir qual dos 3
-- caminhos seguir no vencimento. Assinatura muda de novo -> exige DROP
-- antes do CREATE (erro 42P13 com "create or replace" quando o retorno
-- muda), e o GRANT some junto com o DROP — por isso é repetido no fim
-- deste bloco.
drop function if exists cron_listar_contratos_ativos();

create function cron_listar_contratos_ativos()
returns table (
  id                  uuid,
  imovel_identificacao text,
  inquilino_nome      text,
  telefone_whatsapp   text,
  data_inicio         date,
  data_termino        date,
  indice_reajuste     text,
  valor_aluguel       numeric,
  prazo_indeterminado boolean,
  tipo_renovacao      text
)
language sql
security definer
stable
as $$
  select id, imovel_identificacao, inquilino_nome, telefone_whatsapp,
         data_inicio, data_termino, indice_reajuste, valor_aluguel,
         prazo_indeterminado, tipo_renovacao
  from contracts
  where status = 'ativo';
$$;

grant execute on function cron_listar_contratos_ativos() to cron_batch;

-- ============================================================
-- RPCs do cron (papel agente_ia, escopadas por agent_contract_id()).
-- ATENÇÃO: o nome do papel "agente_ia" abaixo é inferido dos comentários
-- de app/tools/contract_alerts_client.py ("Escreve como agente_ia") — não
-- temos a migration original que criou agent_finalizar_contrato /
-- agent_contract_id() pra confirmar o nome exato do role. Ajuste o GRANT
-- se o nome real for outro.
-- ============================================================

-- Contratos "acionáveis" (requer_aditivo/automatica/nao_identificado) sem
-- decisão até data_termino: desativa e marca a pendência, em vez de
-- finalizar "de vez" como agent_finalizar_contrato faz para novo_contrato.
create function agent_desativar_pendente_renovacao()
returns boolean
language plpgsql
security definer
as $$
declare
  v_contract_id uuid := agent_contract_id();
begin
  update contracts
    set status = 'inativo', pendente_decisao_renovacao = true
    where id = v_contract_id and status = 'ativo';

  if found then
    return true;
  else
    return null;
  end if;
end;
$$;

grant execute on function agent_desativar_pendente_renovacao() to agente_ia;

-- Contratos indeterminado_por_lei: nunca desativam, viram prazo
-- indeterminado automaticamente ao chegar em data_termino sem oposição —
-- mesma coluna prazo_indeterminado da Migration 013, só que agora
-- disparada pelo cron no dia certo, em vez de ajuste manual único.
create function agent_transicionar_prazo_indeterminado()
returns boolean
language plpgsql
security definer
as $$
declare
  v_contract_id uuid := agent_contract_id();
begin
  update contracts
    set prazo_indeterminado = true
    where id = v_contract_id and status = 'ativo' and not prazo_indeterminado;

  if found then
    return true;
  else
    return null;
  end if;
end;
$$;

grant execute on function agent_transicionar_prazo_indeterminado() to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 016
-- ============================================================