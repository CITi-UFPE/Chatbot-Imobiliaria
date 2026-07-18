-- ============================================================
-- MIGRATION 011 — Escrita e dados por contrato pro A2 (Cobrança)
-- ============================================================
-- ATENÇÃO — renumerada de 010 para 011: o A4 (gestão contratual) já ocupou
-- "010" com docs/schemas/010_alertas_contratuais_e_reajuste.sql (ver
-- referência dela no docstring de app/orchestrator/agent_auth.py). Mesma
-- colisão de numeração que já rolou entre A1 e outras branches antes —
-- confirmar o número real antes de rodar, caso mais alguma branch tenha
-- pego "011" nesse meio tempo.
--
-- Depende das Migrations 001, 002, 008 e 009 já terem rodado.
--
-- Duas lacunas que sobraram depois da Migration 008 (leitura em lote via
-- cron_batch) e 009 (motivo atraso_severo):
--
-- 1) agent_update_charge_status (Migration 002) não tem parâmetro nenhum
--    pra dias_atraso ou mensagem_estagio — só status/valor_identificado/
--    data_pagamento. A nota da Migration 008 diz pra usar essa função "já
--    existente" pra atualizar dias_atraso, mas a assinatura dela não
--    suporta isso. Estendendo aqui (drop+create, mesmo padrão que a
--    Migration 005 usou pra agent_open_maintenance_ticket) — se só desse
--    "create or replace", o Postgres trataria como overload novo em vez de
--    substituir, e a versão antiga (sem os campos novos) continuaria
--    coexistindo. Aproveito pra já incluir p_comprovante_url, necessário
--    pro fluxo de leitura de comprovante por visão.
--
-- 2) cron_listar_charges_ativas (Migration 008) devolve só o que basta pra
--    decidir estágio (datas, valores, status) — de propósito NÃO devolve
--    nome/telefone/imóvel (dado pessoal não pertence numa leitura em lote
--    cross-contrato). Depois de identificar que UM contrato específico
--    precisa de ação hoje, o A2 troca pro token normal do agente_ia
--    (contrato por contrato) e usa esta RPC nova pra buscar o que falta —
--    mesmo padrão de buscar_dados_inquilino do A1.
-- ============================================================

-- ------------------------------------------------------------
-- 11.1 — agent_update_charge_status estendida (dias_atraso,
-- mensagem_estagio, comprovante_url, data_identificada_comprovante)
--
-- data_identificada_comprovante existe separada de data_pagamento de
-- propósito: a primeira é "o que a visão computacional leu do comprovante"
-- (pode estar errada), a segunda é "confirmado por um humano" (Fernanda
-- apertando Confirmar) — só a segunda deveria alimentar relatório
-- financeiro. Ver alter table logo abaixo.
-- ------------------------------------------------------------
alter table charges
  add column if not exists data_identificada_comprovante date;

drop function if exists agent_update_charge_status(uuid, text, numeric, date);

create function agent_update_charge_status(
  p_charge_id                     uuid,
  p_status                        text,
  p_valor_identificado            numeric default null,
  p_data_pagamento                date default null,
  p_dias_atraso                   integer default null,
  p_mensagem_estagio              text default null,
  p_comprovante_url               text default null,
  p_data_identificada_comprovante date default null
)
returns void
language plpgsql
security definer
as $$
begin
  update charges
  set status                          = p_status,
      valor_identificado              = coalesce(p_valor_identificado, valor_identificado),
      data_pagamento                  = coalesce(p_data_pagamento, data_pagamento),
      dias_atraso                     = coalesce(p_dias_atraso, dias_atraso),
      mensagem_estagio                = coalesce(p_mensagem_estagio, mensagem_estagio),
      comprovante_url                 = coalesce(p_comprovante_url, comprovante_url),
      data_identificada_comprovante   = coalesce(p_data_identificada_comprovante, data_identificada_comprovante),
      updated_at                      = now()
  where id = p_charge_id
    and contract_id = agent_contract_id(); -- trava de isolamento dentro da própria função
end;
$$;

grant execute on function agent_update_charge_status(
  uuid, text, numeric, date, integer, text, text, date
) to agente_ia;

-- ------------------------------------------------------------
-- 11.2 — buscar_dados_cobranca_contrato: dado pessoal + parâmetros de
-- encargo, escopado por contrato (agent_contract_id()), sem parâmetro.
--
-- ATENÇÃO — unidade de multa_moratoria_percentual não confirmada: o mesmo
-- ponto que a Migration 003 já deixou em aberto pro contrato do ARCO
-- (comment on column contracts.multa_moratoria_percentual). O código Python
-- que consome este campo (app/agents/a2_cobranca/mensagens.py) assume que
-- está na mesma unidade de fração que juros_moratorio_mensal (ex: 0.02 =
-- 2%), não como número inteiro de percentual (ex: 2). Se os dados reais
-- estiverem na outra convenção, os valores de multa nas mensagens de
-- cobrança sairão 100x errados — validar contra pelo menos um contrato
-- real antes de considerar isso pronto pra produção.
-- ------------------------------------------------------------
create or replace function buscar_dados_cobranca_contrato()
returns jsonb
language plpgsql
security definer
as $$
declare
  v_contract_id uuid := agent_contract_id();
  v_result jsonb;
begin
  select jsonb_build_object(
    'telefone_whatsapp', c.telefone_whatsapp,
    'inquilino_nome', c.inquilino_nome,
    'imovel_identificacao', c.imovel_identificacao,
    'multa_moratoria_percentual', c.multa_moratoria_percentual,
    'juros_moratorio_mensal', c.juros_moratorio_mensal
  )
  into v_result
  from contracts c
  where c.id = v_contract_id;

  return v_result;
end;
$$;

grant execute on function buscar_dados_cobranca_contrato() to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 011
-- ============================================================