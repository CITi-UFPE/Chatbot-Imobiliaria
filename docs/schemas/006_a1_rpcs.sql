-- ============================================================
-- MIGRATION 006 — RPCs do Agente 1 (Atendimento ao Inquilino)
-- ============================================================
--
-- Depende das Migrations 001-004 já terem rodado (em especial da função
-- agent_contract_id(), criada na Migration 002, que lê o claim contract_id
-- do JWT assinado por assinar_token_agente()).
--
-- Seguindo o mesmo padrão de agent_create_escalation (Migration 004): as
-- funções abaixo NÃO recebem contract_id como parâmetro. Isso é proposital
-- — o contrato da conversa já está embutido no token, então não faz
-- sentido (e seria uma superfície de erro/ataque desnecessária) deixar o
-- chamador informar de qual contrato ele quer os dados. agent_contract_id()
-- é a única fonte de verdade sobre "qual contrato esta chamada pode ver".
--
-- Decisão de escopo: buscar_dados_inquilino NÃO retorna inquilino_cpf_cnpj,
-- fiador_cpf, banco_agencia, banco_conta nem pix_chave. CPF/CNPJ não tem
-- utilidade pro Agente 1 responder dúvidas sobre o contrato (e expor esse
-- dado por WhatsApp é risco desnecessário), e dados bancários são escopo do
-- A2 (Cobrança), não do A1. Se algum desses campos precisar aparecer no
-- futuro, adicionar explicitamente — não copiar o SELECT * da tabela.
-- ============================================================

create or replace function buscar_dados_inquilino()
returns jsonb
language plpgsql
security definer
as $$
declare
  v_contract_id uuid := agent_contract_id();
  v_result jsonb;
begin
  select jsonb_build_object(
    'contract_id', c.id,
    'tipo_locatario', c.tipo_locatario,
    'inquilino_nome', c.inquilino_nome,
    'responsavel_contato_nome', c.responsavel_contato_nome,
    'valor_aluguel', c.valor_aluguel,
    'dia_vencimento', c.dia_vencimento,
    'vencimento_mes_referencia', c.vencimento_mes_referencia,
    'data_inicio', c.data_inicio,
    'data_termino', c.data_termino,
    'indice_reajuste', c.indice_reajuste,
    'data_aniversario_reajuste', c.data_aniversario_reajuste,
    'garantia_tipo', c.garantia_tipo,
    'garantia_valor', c.garantia_valor,
    'fiador_nome', c.fiador_nome,
    'multa_infracao_tipo', c.multa_infracao_tipo,
    'multa_infracao_valor', c.multa_infracao_valor,
    'multa_moratoria_percentual', c.multa_moratoria_percentual,
    'juros_moratorio_mensal', c.juros_moratorio_mensal,
    'aviso_previo_dias', c.aviso_previo_dias,
    'aviso_previo_a_partir_mes', c.aviso_previo_a_partir_mes,
    'imovel_identificacao', c.imovel_identificacao,
    'imovel_endereco', c.imovel_endereco,
    'clausulas', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'numero_clausula', cl.numero_clausula,
        'titulo_clausula', cl.titulo_clausula,
        'texto_clausula', cl.texto_clausula,
        'categoria', cl.categoria
      )), '[]'::jsonb)
      from contract_clauses cl
      where cl.contract_id = c.id
    )
  )
  into v_result
  from contracts c
  where c.id = v_contract_id;

  return v_result;
end;
$$;

grant execute on function buscar_dados_inquilino() to agente_ia;

-- ------------------------------------------------------------
-- consultar_historico — UNION de maintenance_tickets, charge_negotiations
-- (via join com charges, já que charge_negotiations não tem contract_id
-- direto) e escalations. contract_alerts e conversation_logs ficam de fora
-- por decisão de escopo (alertas são internos pra gestora; conversation_logs
-- é o log bruto da conversa, não um "atendimento").
-- ------------------------------------------------------------
create or replace function consultar_historico(
  p_limite int default 10,
  p_tipo text default 'todos'
)
returns jsonb
language plpgsql
security definer
as $$
declare
  v_contract_id uuid := agent_contract_id();
  v_result jsonb;
begin
  select coalesce(jsonb_agg(h order by h.criado_em desc), '[]'::jsonb)
  into v_result
  from (
    select
      mt.id::text as id,
      'manutencao'::text as tipo,
      mt.status,
      format(
        'Chamado de manutenção (%s, urgência %s): %s',
        mt.categoria, mt.urgencia, mt.descricao
      ) as resumo,
      mt.data_abertura as criado_em
    from maintenance_tickets mt
    where mt.contract_id = v_contract_id
      and (p_tipo = 'todos' or p_tipo = 'manutencao')

    union all

    select
      cn.id::text as id,
      'cobranca'::text as tipo,
      coalesce(cn.tipo_resolucao, 'em_negociacao') as status,
      format(
        'Negociação de cobrança: %s%s',
        coalesce(cn.tipo_resolucao, 'em andamento'),
        case when cn.valor_negociado is not null
          then format(' (valor negociado: R$ %s)', cn.valor_negociado)
          else ''
        end
      ) as resumo,
      cn.created_at as criado_em
    from charge_negotiations cn
    join charges ch on ch.id = cn.charge_id
    where ch.contract_id = v_contract_id
      and (p_tipo = 'todos' or p_tipo = 'cobranca')

    union all

    select
      e.id::text as id,
      'escalonamento'::text as tipo,
      e.status,
      format('Escalonamento (%s): %s', e.motivo, coalesce(e.descricao, 'sem descrição')) as resumo,
      e.created_at as criado_em
    from escalations e
    where e.contract_id = v_contract_id
      and (p_tipo = 'todos' or p_tipo = 'escalonamento')

    order by criado_em desc
    limit p_limite
  ) h;

  return v_result;
end;
$$;

grant execute on function consultar_historico(int, text) to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 006
-- ============================================================