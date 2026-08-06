-- ============================================================
-- MIGRATION 014 — Dados de pagamento (Pix/banco) no A1
-- ============================================================
-- Reverte parcialmente uma decisão de escopo da Migration 006, que excluiu
-- deliberadamente banco_agencia/banco_conta/pix_chave de
-- buscar_dados_inquilino com o argumento "dados bancários são escopo do A2
-- (Cobrança), não do A1".
--
-- Motivo da reversão: essa decisão presumia que o A2 responderia esse tipo
-- de pergunta por texto — mas o A2 nunca teve (e não vai ganhar agora)
-- capacidade de conversar por texto, ele só reage a comprovante (imagem) e
-- clique de botão da Fernanda (ver app/orchestrator/orchestrator.py). Isso
-- deixou um buraco real: "qual a chave Pix pra eu pagar?" não tinha
-- resposta nenhuma em lugar algum do sistema. Confirmado com o Davi
-- (30/07/2026) que faz sentido o A1 responder isso — é informação de baixo
-- risco que todo inquilino eventualmente precisa.
--
-- Ainda EXCLUÍDOS de propósito (não mudou): inquilino_cpf_cnpj, fiador_cpf
-- — sem utilidade para responder dúvida de contrato, e expor CPF por
-- WhatsApp é risco desnecessário que essa migration não reavalia.
--
-- create or replace function é seguro aqui sem DROP: o tipo de retorno
-- continua sendo `jsonb` (um blob), só adicionamos chaves novas dentro do
-- jsonb_build_object — diferente do caso de cron_listar_contratos_ativos
-- (Migration 012), que usa `returns table(...)` com colunas nomeadas e por
-- isso exige DROP antes de mudar a assinatura.
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

-- create or replace preserva o GRANT já existente (Migration 006) — não
-- precisa reconceder, diferente do caso de returns table.

-- ============================================================
-- FIM DA MIGRATION 014
-- ============================================================
