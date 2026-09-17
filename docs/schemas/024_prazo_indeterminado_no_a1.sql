-- ============================================================
-- MIGRATION 024 — prazo_indeterminado visível para o A1
-- ============================================================
-- Bug encontrado em teste real (contrato do Elias, prazo indeterminado
-- desde a Migration 013): "quando meu contrato termina?" respondia só com
-- a data crua de contracts.data_termino ("Seu contrato termina em
-- 02/11/2026") — sem nenhuma menção a estar em prazo indeterminado. A causa
-- raiz: a Migration 013 adicionou a coluna prazo_indeterminado e atualizou
-- cron_listar_contratos_ativos() (usada pelo A4/cron) para devolvê-la, mas
-- NUNCA atualizou buscar_dados_inquilino() (usada pelo A1) — o campo
-- simplesmente não existia no retorno que o A1 vê. Sem essa informação, o
-- modelo não tinha como saber que data_termino, pra esse contrato, é só um
-- valor histórico/decorativo (ver comentário da própria coluna, Migration
-- 013): "data_termino permanece preenchida (valor histórico, não usado
-- para decisão)".
--
-- Único campo novo adicionado ao retorno: prazo_indeterminado. O
-- SYSTEM_PROMPT do A1 (app/agents/a1_atendimento/atendimento.py) passa a
-- explicar em linguagem simples quando esse campo é true, em vez de citar
-- 'termina em' com uma data que não é mais real.
--
-- create or replace é seguro aqui sem DROP (mesmo racional da Migration
-- 014): o tipo de retorno continua jsonb, só adiciona uma chave no
-- jsonb_build_object.
-- ============================================================

begin;

create or replace function public.buscar_dados_inquilino()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_contract_id uuid := public.agent_contract_id();
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
    'prazo_indeterminado', c.prazo_indeterminado,
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
    'banco_agencia', c.banco_agencia,
    'banco_conta', c.banco_conta,
    'pix_chave', c.pix_chave,
    'clausulas', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'numero_clausula', cl.numero_clausula,
        'titulo_clausula', cl.titulo_clausula,
        'texto_clausula', cl.texto_clausula,
        'categoria', cl.categoria
      )), '[]'::jsonb)
      from public.contract_clauses cl
      where cl.contract_id = c.id
    )
  )
  into v_result
  from public.contracts c
  where c.id = v_contract_id;

  return v_result;
end;
$$;

-- create or replace preserva o GRANT já existente (Migration 006/014) —
-- não precisa reconceder, mesma nota das migrations anteriores desta RPC.

comment on function public.buscar_dados_inquilino() is
  'Dados estruturados do contrato do inquilino desta conversa, para o A1. A partir da Migration 024 inclui prazo_indeterminado (Migration 013) — sem isso o A1 não tinha como saber que data_termino, para contratos renovados por inércia, é só um valor histórico.';

commit;

-- ============================================================
-- FIM DA MIGRATION 024
-- ============================================================
