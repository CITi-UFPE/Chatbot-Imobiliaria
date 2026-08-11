-- ============================================================
-- MIGRATION 018 — decisao_gestora também resolve os alertas de
-- renovação D-60 (Projeto Domingos Monteiro)
-- ============================================================
-- Contexto: a Migration 016 criou o card de renovação em
-- RenovacaoSection.tsx (tela de dashboard) para contratos "acionáveis"
-- (requer_aditivo / automatica / nao_identificado), mas a resolução desse
-- card (botão "Definir renovação" ou "Confirmar encerramento") só
-- escrevia em contracts — nunca em contract_alerts. Resultado: o alerta
-- de renovação ficava para sempre com decisao_gestora='pendente', então
-- o card nunca saía da lista (RenovacaoSection.tsx filtra por
-- tipo='alerta_renovacao_d60' sem olhar decisão), mesmo depois de a
-- gestora já ter resolvido pelo dashboard.
--
-- decisao_gestora já existe em contract_alerts e já é usada pelo Fluxo B
-- (cálculo de reajuste D-30 — ver app/agents/a4_gestao_contratual/
-- fluxo.py::_aplicar_reajustes_confirmados, que lê via
-- cron_listar_reajustes_para_aplicar) com os valores 'pendente',
-- 'renovar_sugerido', 'renovar_ajustado' e 'encerrar'. Em vez de criar uma
-- coluna nova só para o Fluxo A (renovação), esta migration reaproveita a
-- mesma coluna, adicionando dois valores novos, exclusivos do tipo
-- 'alerta_renovacao_d60':
--   - 'renovado':  gestora definiu a renovação (nova data ou prazo
--                  indefinido) pelo dialog DecisaoRenovacaoDialog em
--                  RenovacaoSection.tsx.
--   - 'encerrado': gestora confirmou o encerramento de um contrato que
--                  já estava inativo por falta de decisão até
--                  data_termino (botão "Confirmar encerramento" em
--                  RenovacaoSection.tsx).
--
-- Valor dedicado (em vez de reaproveitar 'encerrar', que já existe para o
-- Fluxo B) por segurança: não temos o SQL de cron_listar_reajustes_para_aplicar
-- para confirmar que o filtro dela é escopado por tipo do alerta, então
-- evitamos qualquer risco de uma linha de 'alerta_renovacao_d60' marcada
-- como 'encerrar' ser lida por engano pelo Fluxo B. 'encerrado' garante
-- isolamento total entre os dois fluxos sem depender dessa confirmação.
-- Todo leitor de decisao_gestora continua escopado por tipo do alerta
-- (RenovacaoSection.tsx filtra tipo='alerta_renovacao_d60') — os dois
-- fluxos nunca leem a coluna decisao_gestora um do outro.
-- ============================================================

alter table contract_alerts drop constraint contract_alerts_decisao_gestora_check;

alter table contract_alerts add constraint contract_alerts_decisao_gestora_check
  check (decisao_gestora = any (array[
    'pendente'::text, 'renovar_sugerido'::text, 'renovar_ajustado'::text,
    'encerrar'::text, 'renovado'::text, 'encerrado'::text
  ]));

-- ============================================================
-- FIM DA MIGRATION 018
-- ============================================================