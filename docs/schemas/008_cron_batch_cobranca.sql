-- ============================================================
-- MIGRATION 008 — Papel cron_batch e leitura cross-contrato para jobs
-- agendados (Agente 2 — Cobrança)
-- ============================================================
-- Depende das Migrations 001 e 002 já terem rodado.
--
-- Problema que esta migration resolve: todo o modelo de RLS do projeto
-- (agent_contract_id(), seção 2.2 da Migration 002) presume UMA conversa =
-- UM contrato — o token "agente_ia" só enxerga o contract_id embutido no
-- próprio JWT. Isso é correto e desejado pro fluxo de mensagem do WhatsApp,
-- mas o cron diário de cobrança (app/jobs/cron_cobranca_diaria.py) não é
-- uma conversa: ele precisa varrer TODOS os contratos ativos de uma vez pra
-- decidir quem está em D-5/D0/D+5/D+10/D+15 hoje. Isso é estruturalmente
-- impossível com o token agente_ia atual — e a resposta errada seria usar
-- a service_role key só pra resolver isso (perderíamos toda a superfície
-- de auditoria/restrição que o resto do projeto tem).
--
-- Solução: um papel novo, dedicado e só de LEITURA em lote, "cron_batch".
--   - Não recebe contract_id nenhum no JWT (não faz sentido, é cross-contrato
--     por definição).
--   - Não recebe GRANT de SELECT direto nas tabelas — só EXECUTE na função
--     de listagem abaixo, que decide exatamente quais colunas saem.
--   - Não escreve nada. Toda escrita (dar baixa em cobrança, atualizar
--     dias_atraso/status) continua indo contrato por contrato, com o JWT
--     normal do agente_ia (via assinar_token_agente) e a RPC já existente
--     agent_update_charge_status (Migration 002, seção 2.9) — o cron_batch
--     só existe pra resolver o "quem eu preciso olhar hoje", nunca o "e
--     agora eu mudo o quê".
--
-- Nenhuma configuração nova é necessária no dashboard do Supabase: o
-- cron_batch reaproveita a MESMA Standby Key HS256 (SUPABASE_JWT_SECRET)
-- já configurada para o agente_ia (docs/setup-supabase.md, seção 5) — só
-- muda o valor do claim "role" no token assinado. Ver
-- app/orchestrator/agent_auth.py — assinar_token_cron_batch /
-- obter_client_cron_batch.
-- ============================================================

-- ------------------------------------------------------------
-- cron_listar_charges_ativas — cross-contrato, só leitura, só os campos
-- necessários pra decidir estágio de cobrança (D-5/D0/D+5/D+10/D+15).
-- Não retorna nada de identificação pessoal (nome, telefone, CPF) nem
-- dados bancários — se o A2 precisar disso pra alguma ação específica de
-- UM contrato (ex: montar a mensagem de cobrança), isso é resolvido depois,
-- contrato por contrato, com o JWT normal do agente_ia (mesmo padrão do A1
-- em buscar_dados_inquilino) — não nesta função de listagem em lote.
--
-- Exclui charges com status='quitado': o cron não precisa reavaliar
-- cobrança já paga todo santo dia.
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
    and ch.status <> 'quitado';
$$;

-- ------------------------------------------------------------
-- Papel dedicado do cron ("cron_batch") — mesmo padrão de criação do
-- agente_ia (Migration 002, seção 2.10), mas SEM nenhum grant de SELECT
-- nas tabelas base: o único jeito de ler algo com este papel é através da
-- função de listagem acima, que já decide o recorte de colunas permitido.
-- ------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'cron_batch') then
    create role cron_batch nologin;
  end if;
end
$$;

grant cron_batch to authenticator; -- necessário para o PostgREST poder assumir esse papel
grant usage on schema public to cron_batch;
grant execute on function cron_listar_charges_ativas() to cron_batch;

-- Reforço explícito (mesma doutrina da seção 2.8 da Migration 002):
-- segurança por revogação explícita é auditável, segurança por "nunca
-- concedemos" não é.
revoke select, insert, update, delete on
  contracts, contract_clauses, charges, charge_negotiations,
  maintenance_tickets, escalations, contract_alerts, conversation_logs,
  agent_conversation_states
from cron_batch;

-- ============================================================
-- FIM DA MIGRATION 008
--
-- Nota pro Agente 2 (Daniel): esta migration resolve só a leitura em lote.
-- A lógica de decidir o que fazer com cada charge (compor mensagem, marcar
-- estágio, escalar em D+15 — ver Migration 009, motivo 'atraso_severo') e
-- de fato gravar isso (via agent_update_charge_status, contrato por
-- contrato) continua sendo trabalho do app/agents/a2_cobranca/.
-- ============================================================
