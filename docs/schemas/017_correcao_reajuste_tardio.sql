-- ============================================================
-- MIGRATION 017 — Correção: reajuste confirmado após o aniversário
-- nunca era aplicado (Projeto Domingos Monteiro)
-- ============================================================
-- Bug encontrado ao testar o Fluxo B do A4 (D-30/aplicação): a função
-- criada na Migration 010, seção 10.3, usa IGUALDADE EXATA de data para
-- decidir quais reajustes aplicar hoje:
--
--   where ... and data_disparo + 30 = p_data_referencia ...
--
-- Isso só captura o reajuste no ÚNICO dia exato em que o aniversário do
-- contrato coincide com "hoje" (data_disparo + 30 dias). Se a gestora
-- confirmar a decisão (decisao_gestora -> 'renovar_sugerido' ou
-- 'renovar_ajustado') ANTES do aniversário, funciona normalmente. Se ela
-- confirmar DEPOIS — mesmo que só 1 dia depois — essa igualdade nunca
-- mais vai ser verdadeira em nenhuma execução futura do cron, e o
-- reajuste fica com decisao_gestora confirmada e valor_aplicado NULL
-- para sempre, sem nenhum erro visível indicando isso.
--
-- Correção: trocar "=" por "<=". Uma vez aplicado, valor_aplicado deixa
-- de ser NULL e a linha não é mais listada (mesmo filtro de sempre) — não
-- há risco de reaplicar o mesmo reajuste duas vezes, nem de "acumular"
-- reajustes: cada contrato só tem UM registro de calculo_reajuste_d30 em
-- aberto por vez (o próximo só é criado no aniversário seguinte, um ano
-- depois, por processar_calculo_reajuste).
--
-- create or replace function é suficiente aqui — a assinatura (parâmetros
-- e colunas de retorno) não muda, só o corpo, então não há necessidade do
-- DROP + GRANT que outras migrations deste projeto precisaram quando a
-- assinatura mudava (ver comentário equivalente nas Migrations 012/014).
-- ============================================================

create or replace function cron_listar_reajustes_para_aplicar(p_data_referencia date)
returns table (
  alerta_id      uuid,
  contract_id    uuid,
  valor_sugerido numeric
)
language sql
security definer
stable
as $$
  select id, contract_id, valor_sugerido
  from contract_alerts
  where tipo = 'calculo_reajuste_d30'
    and data_disparo + 30 <= p_data_referencia
    and decisao_gestora in ('renovar_sugerido', 'renovar_ajustado')
    and valor_aplicado is null;
$$;

-- create or replace não apaga GRANTs existentes (diferente de drop
-- function) — este grant é só defensivo, pro caso de esta migration
-- rodar num banco onde a 010 nunca chegou a conceder (ex: ambiente criado
-- direto a partir de um dump mais recente).
grant execute on function cron_listar_reajustes_para_aplicar(date) to cron_batch;

-- ============================================================
-- FIM DA MIGRATION 017
-- ============================================================