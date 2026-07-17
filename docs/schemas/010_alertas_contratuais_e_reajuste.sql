-- ============================================================
-- MIGRATION 010 — Alertas contratuais e reajuste (A4 — Gestão Contratual)
-- ============================================================
-- Renumerada de 006 para 010: quando esta branch foi criada, 006-009 ainda
-- estavam livres; origin/develop ocupou todos os quatro nesse meio tempo
-- (006_a1_rpcs.sql, 007_estado_conversa_agente.sql,
-- 008_cron_batch_cobranca.sql, 009_escalation_atraso_severo.sql) — ver
-- docs/specs/a4-ajustes-pre-merge.md, Parte 1, item 2.
--
-- Depende das Migrations 001 e 002 já terem rodado (é o mínimo técnico:
-- tabela contracts/contract_alerts e agent_contract_id()/agente_ia). Não
-- depende estritamente da Migration 008 (origin/develop) ter rodado antes —
-- a seção 10.3 abaixo cria o papel "cron_batch" de forma defensiva
-- (create role if not exists), então esta migration funciona tanto isolada
-- quanto depois de 008 já ter criado o mesmo papel para o A2.
--
-- Três mudanças, todas para o A4 (docs/specs/agente-gestao-contratual.md):
--
-- 1) contracts.indice_reajuste passa a aceitar 'ipca' além de 'igpm' e
--    'livre_negociacao' — o Fluxo B (cálculo de reajuste) do A4 suporta os
--    dois índices, buscando o percentual acumulado de 12 meses na API
--    pública do Banco Central (SGS).
--
-- 2) Índice único em contract_alerts para idempotência: o job diário do A4
--    roda 1x/dia, mas se rodar de novo no mesmo dia (retry, deploy, falha
--    de rede) não pode gerar um segundo alerta/mensagem duplicada para o
--    mesmo contrato — mesmo padrão de charges_unico_por_mes (Migration 001).
--
-- 3) Leitura em lote via "cron_batch" (papel de origin/develop, Migration
--    008 — reaproveitado aqui, não um papel próprio do A4) + 3 funções
--    novas de escrita no papel "agente_ia" já existente:
--
--    O job diário do A4 precisa enxergar TODOS os contratos ativos de uma
--    vez para decidir quais entraram na janela de alerta — não existe
--    contract_id nenhum para escopar essa LEITURA nesse momento. Essa
--    doutrina já foi resolvida uma vez em origin/develop para o mesmo
--    problema no A2 (cron de cobrança): um papel dedicado, só leitura,
--    "cron_batch", com GRANT EXECUTE só nas funções de listagem em lote que
--    cada agente precisa — nunca GRANT direto de SELECT nas tabelas, e
--    nunca escrita. Em vez de criar um segundo papel batch (ex: "job_ia")
--    fazendo exatamente a mesma coisa com outro nome, o A4 estende o
--    cron_batch existente com as suas próprias 3 funções de listagem.
--
--    A ESCRITA é outra história: registrar um alerta ou aplicar um reajuste
--    é sempre uma ação sobre UM contrato específico, então não há razão
--    para abrir mão do isolamento por contrato que agent_contract_id() já
--    garante via RLS. As 3 funções de escrita (seção 10.4) usam o papel
--    agente_ia de sempre — o job assina um token por contrato
--    (obter_client_agente(contract_id)) na hora de escrever, exatamente
--    como o agente conversacional já faz. cron_batch nunca escreve nada.
-- ============================================================

-- ------------------------------------------------------------
-- 10.1 — 'ipca' como índice de reajuste válido
-- ------------------------------------------------------------
do $$
declare
  v_constraint_name text;
begin
  select con.conname into v_constraint_name
  from pg_constraint con
  join pg_class rel on rel.oid = con.conrelid
  where rel.relname = 'contracts'
    and con.contype = 'c'
    and pg_get_constraintdef(con.oid) like '%indice_reajuste%'
  limit 1; -- select ... into é escalar: sem limit 1, uma 2ª constraint que também
           -- mencione indice_reajuste (ex: futura constraint composta) faria isto
           -- falhar com "too many rows" em vez de só pegar a primeira ocorrência.

  if v_constraint_name is not null then
    execute format('alter table contracts drop constraint %I', v_constraint_name);
  end if;
end
$$;

alter table contracts add constraint contracts_indice_reajuste_check
  check (indice_reajuste in ('igpm', 'ipca', 'livre_negociacao'));

-- ------------------------------------------------------------
-- 10.2 — Idempotência do alerta diário
-- ------------------------------------------------------------
create unique index if not exists contract_alerts_unico_por_disparo
  on contract_alerts (contract_id, tipo, data_disparo);

-- ------------------------------------------------------------
-- 10.3 — Leitura em lote do A4 via "cron_batch" (papel de origin/develop)
-- ------------------------------------------------------------
-- Bloco defensivo: cria o papel só se ele ainda não existir (idempotente
-- com a criação equivalente em 008_cron_batch_cobranca.sql, caso esta
-- migration rode antes, depois, ou sem 008 ter rodado nesta branch).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'cron_batch') then
    create role cron_batch nologin;
  end if;
end
$$;

grant cron_batch to authenticator; -- necessário para o PostgREST poder assumir esse papel
grant usage on schema public to cron_batch;

-- Lista os contratos ativos com os campos que o A4 precisa para decidir
-- se algum entrou na janela de alerta (D-60) ou de reajuste (D-30). Não
-- depende de agent_contract_id() — é exatamente o caso de uso que essa
-- trava não cobre (o job não representa UMA conversa/contrato).
create or replace function cron_listar_contratos_ativos()
returns table (
  id                  uuid,
  imovel_identificacao text,
  inquilino_nome      text,
  telefone_whatsapp   text,
  data_inicio         date,
  data_termino        date,
  indice_reajuste     text,
  valor_aluguel       numeric
)
language sql
security definer
stable
as $$
  select id, imovel_identificacao, inquilino_nome, telefone_whatsapp,
         data_inicio, data_termino, indice_reajuste, valor_aluguel
  from contracts
  where status = 'ativo';
$$;

-- Cláusulas financeiras do contrato (categoria já existe desde a Migration
-- 001) — o A4 procura nelas, por palavra-chave em Python, qual cláusula
-- menciona o reajuste, pra citar o número na mensagem à gestora.
create or replace function cron_listar_clausulas_financeiras(p_contract_id uuid)
returns table (
  numero_clausula text,
  texto_clausula  text
)
language sql
security definer
stable
as $$
  select numero_clausula, texto_clausula
  from contract_clauses
  where contract_id = p_contract_id and categoria = 'financeiro';
$$;

-- Lista alertas de reajuste confirmados ou ajustados pela gestora
-- (staff_full_access, RLS já existente) cujo aniversário (data_disparo + 30
-- dias) é a data de referência — ou seja, "hoje é o dia de aplicar". Só
-- 'renovar_sugerido'/'renovar_ajustado' fazem sentido para calculo_reajuste
-- (o valor final decidido pela gestora é sempre valor_sugerido — se ela
-- ajustou, a edição já sobrescreveu essa coluna direto via staff_full_access,
-- não existe uma segunda coluna "valor_ajustado"). 'encerrar' não se aplica
-- aqui (é uma decisão do Fluxo A, sobre renovação, não sobre reajuste) e
-- valor_aplicado is null evita reaplicar um alerta já processado. Mesmo
-- filtro é reforçado dentro de agent_aplicar_reajuste (seção 10.4) — esta
-- função decide o que ENTRA no lote do dia, a de escrita decide se ainda é
-- válido aplicar no momento exato da escrita (defesa em profundidade).
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
    and data_disparo + 30 = p_data_referencia
    and decisao_gestora in ('renovar_sugerido', 'renovar_ajustado')
    and valor_aplicado is null;
$$;

grant execute on function cron_listar_contratos_ativos() to cron_batch;
grant execute on function cron_listar_clausulas_financeiras(uuid) to cron_batch;
grant execute on function cron_listar_reajustes_para_aplicar(date) to cron_batch;

-- cron_batch só tem GRANT EXECUTE nas funções de listagem (as 3 acima +
-- cron_listar_charges_ativas do A2, Migration 008) — nunca SELECT direto. O
-- revoke abaixo é redundante com o que 008 já faz (um papel só tem os
-- GRANTs que recebeu explicitamente), mas repetido aqui porque esta
-- migration precisa funcionar mesmo rodando isolada, sem 008: segurança por
-- revogação explícita é auditável, segurança por "nunca concedemos" não é.
revoke select, insert, update, delete on
  contracts, contract_clauses, charges, charge_negotiations,
  maintenance_tickets, escalations, contract_alerts, conversation_logs
from cron_batch;

-- ------------------------------------------------------------
-- 10.4 — Escrita do A4 via "agente_ia" (não via cron_batch)
-- ------------------------------------------------------------
-- Mesmo padrão de agent_update_charge_status / agent_open_maintenance_ticket
-- (Migration 002, seção 2.9): a função nem recebe contract_id como
-- parâmetro — lê agent_contract_id() direto do claim do JWT. Isso é
-- estritamente mais seguro que validar um p_contract_id recebido contra
-- agent_contract_id(): não existe a possibilidade de passar o contrato
-- errado, porque o parâmetro simplesmente não existe.
--
-- Quem chama (app/tools/contract_alerts_client.py) assina um token por
-- contrato com obter_client_agente(contract_id) antes de cada uma dessas
-- chamadas — o job em lote nunca reusa o token de leitura (cron_batch) para
-- escrever.

-- Registra o alerta de renovação D-60. ON CONFLICT DO NOTHING usando o
-- índice único da seção 10.2: se o job rodar duas vezes no mesmo dia para
-- o mesmo contrato, a segunda chamada não insere nem devolve linha nova —
-- quem chama sabe (por id = null) que não deve reenviar a mensagem.
create or replace function agent_registrar_alerta_renovacao(
  p_data_disparo date
)
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  insert into contract_alerts (contract_id, tipo, data_disparo, decisao_gestora)
  values (agent_contract_id(), 'alerta_renovacao_d60', p_data_disparo, 'pendente')
  on conflict (contract_id, tipo, data_disparo) do nothing
  returning id into v_id;

  return v_id;
end;
$$;

-- Registra o cálculo de reajuste D-30, já com o percentual e o valor
-- sugerido calculados em Python (busca do índice na API do Banco Central
-- não é responsabilidade do banco).
create or replace function agent_registrar_calculo_reajuste(
  p_data_disparo date,
  p_percentual_reajuste numeric,
  p_valor_sugerido numeric
)
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  insert into contract_alerts (
    contract_id, tipo, data_disparo, percentual_reajuste, valor_sugerido, decisao_gestora
  )
  values (
    agent_contract_id(), 'calculo_reajuste_d30', p_data_disparo, p_percentual_reajuste, p_valor_sugerido, 'pendente'
  )
  on conflict (contract_id, tipo, data_disparo) do nothing
  returning id into v_id;

  return v_id;
end;
$$;

-- Aplica o reajuste confirmado/ajustado pela gestora: atualiza o aluguel
-- vigente do contrato e marca o alerta como aplicado (valor_aplicado), na
-- mesma transação — nunca um sem o outro. A escrita em contract_alerts
-- carrega o MESMO filtro de cron_listar_reajustes_para_aplicar
-- (decisao_gestora confirmada + valor_aplicado ainda null) — não é
-- redundante: entre o momento em que o job LEU a lista do dia e o momento
-- em que chega a vez de aplicar ESTE item, algo pode ter mudado (retry
-- concorrente, decisão da gestora revertida). "returning id into v_id" só
-- preenche se a linha bateu nas condições; se não bateu, v_id fica null e o
-- UPDATE em contracts nem roda — quem chama sabe (pelo retorno null) que
-- nada foi aplicado, em vez de assumir sucesso silencioso.
create or replace function agent_aplicar_reajuste(
  p_alerta_id uuid,
  p_valor_aplicado numeric
)
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  update contract_alerts
  set valor_aplicado = p_valor_aplicado
  where id = p_alerta_id
    and contract_id = agent_contract_id()
    and decisao_gestora in ('renovar_sugerido', 'renovar_ajustado')
    and valor_aplicado is null
  returning id into v_id;

  if v_id is not null then
    update contracts
    set valor_aluguel = p_valor_aplicado,
        updated_at = now()
    where id = agent_contract_id();
  end if;

  return v_id;
end;
$$;

grant execute on function agent_registrar_alerta_renovacao(date) to agente_ia;
grant execute on function agent_registrar_calculo_reajuste(date, numeric, numeric) to agente_ia;
grant execute on function agent_aplicar_reajuste(uuid, numeric) to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 010
-- ============================================================
