# Setup do Supabase — Projeto Domingos

Este documento registra como o projeto Supabase de produção foi criado e configurado, para quem entrar no time depois não depender de reconstruir esse histórico. Nenhum segredo real aparece aqui — só nomes de variáveis e onde encontrar cada valor no dashboard.

Para rodar a suíte de testes de integração (`pytest -m integration`) contra um projeto Supabase separado, só de teste, ver `tests/integration/README.md` — o setup de projeto/migrations é o mesmo processo descrito aqui, aplicado a um segundo projeto.

## 1. Projeto

- Nome: **Chatbot-Imobiliaria**
- Região: **South America (São Paulo) — `sa-east-1`**
- Motivo da região: latência (backend e usuários no Brasil) e residência de dados (relevante para conformidade com a LGPD).
- Atenção: a região de um projeto Supabase **não pode ser alterada depois de criado**. Se precisar trocar, é preciso criar um projeto novo e migrar.
- Project ID: `pjdetppxafsrcpbqjkka` (usado na URL do projeto: `https://pjdetppxafsrcpbqjkka.supabase.co`).

## 2. Migrations

As migrations vivem em `docs/schemas/`:

- `001_create_tables.sql` — cria as 8 tabelas de negócio (contracts, contract_clauses, charges, charge_negotiations, maintenance_tickets, escalations, contract_alerts, conversation_logs), com constraints de integridade e RLS habilitado (sem políticas ainda — fail-closed proposital).
- `002_auth_rbac_rls.sql` — cria `staff_users`, as políticas de RLS de todas as tabelas, as funções RPC de escrita do agente (`agent_update_charge_status`, `agent_open_maintenance_ticket`, `agent_create_escalation`, `agent_log_message`), o papel dedicado `agente_ia`, e o bucket privado de Storage `contracts`.
- `003_ajusta_categorias_clausulas.sql` — categorias novas de `contract_clauses.categoria` (objeto do contrato, prazo/vigência, alienação, desapropriação, foro — antes forçadas em "rescisao" por falta de categoria própria) e campos de endereço do locatário/fiador (antes só existia o endereço do imóvel).
- `004_protocolo_e_resolucao_contrato.sql` — protocolo sequencial real em `agent_create_escalation` (formato `ESC-YYYY-NNNNN`, antes sempre `NULL`) e a função `resolver_contrato_por_telefone` (papel `anon`, usada pelo backend para descobrir o `contract_id` de uma mensagem recém-chegada do WhatsApp, antes de existir um token assinado).
- `005_ticket_manutencao_protocolo.sql` — protocolo sequencial em `maintenance_tickets` (formato `MNT-YYYY-NNNN`) e colunas para os sinais de classificação do A3 (risco extraído pelo LLM, marcação de classificação incerta).
- `006_a1_rpcs.sql` — RPCs de leitura do A1 (Atendimento), em especial `buscar_dados_inquilino`, sempre escopadas por `agent_contract_id()` (nunca recebem `contract_id` como parâmetro).
- `007_estado_conversa_agente.sql` — tabela `agent_conversation_states` + RPCs `agent_get/set/clear_conversation_state`, genéricas para qualquer agente multi-turno (hoje só o A3 usa).
- `008_cron_batch_cobranca.sql` — papel `cron_batch` (leitura cross-contrato, só via RPC `cron_listar_charges_ativas`, sem GRANT direto em tabela nenhuma) para os jobs agendados do A2.
- `009_escalation_atraso_severo.sql` — adiciona `atraso_severo` à lista de `escalations.motivo`, para o cron do A2 escalar inadimplência D+15.
- `010_alertas_contratuais_e_reajuste.sql` — base do A4 (Gestão Contratual): `indice_reajuste` passa a aceitar `'ipca'`, índice único em `contract_alerts` para idempotência do job diário, `cron_listar_contratos_ativos`/`cron_listar_clausulas_financeiras`/`cron_listar_reajustes_para_aplicar` (leitura em lote via `cron_batch`) e `agent_registrar_alerta_renovacao`/`agent_registrar_calculo_reajuste`/`agent_aplicar_reajuste` (escrita via `agente_ia`, escopada por contrato).
- `011_a2_cobranca_rpcs.sql` — estende `agent_update_charge_status` com `dias_atraso`/`mensagem_estagio`/`comprovante_url`/`data_identificada_comprovante`, e adiciona `buscar_dados_cobranca_contrato` — suporte de banco para o cron diário do A2 avançar estágios de cobrança (D-5/D0/D+5/D+10/D+15).
- `012_finalizacao_contrato_automatica.sql` — `agent_finalizar_contrato`: desativa (`status = 'inativo'`) o contrato da chamada atual quando chega em `data_termino`, incondicional (sem decisão da gestora) e idempotente (`where status = 'ativo'` como guard).
- `013_prazo_indeterminado.sql` — coluna `contracts.prazo_indeterminado` (contratos renovados por inércia, ex: cláusula 3.3 — `data_termino` fica só como valor histórico/decorativo). O Fluxo A do A4 (alerta de renovação) e a finalização automática (Migration 012) pulam esses contratos deliberadamente.
- `014_dados_pagamento_no_a1.sql` — reverte parcialmente o escopo da Migration 006: `buscar_dados_inquilino` passa a incluir `banco_agencia`/`banco_conta`/`pix_chave` (o A2 nunca ganhou capacidade de conversar por texto, então "qual a chave Pix?" não tinha resposta em lugar nenhum). CPF/CNPJ do inquilino e do fiador continuam excluídos de propósito.
- `015_agente_com_conversa_ativa.sql` — `agent_get_active_agent()`: devolve o agente dono de uma conversa multi-turno em aberto pra este contrato (se houver), para `rotear_mensagem` (app/orchestrator/orchestrator.py) pular o classificador e ir direto pro A3 quando já existir uma máquina de estados em andamento — evita que uma resposta ambígua no meio do fluxo (ex: "hein? que endereço?") seja desviada pra outro agente.

**Rodar sempre nessa ordem** (001 antes do 002, e assim por diante — várias migrations posteriores dependem de funções/colunas criadas nas anteriores) via **SQL Editor** do dashboard: cole o conteúdo do arquivo, clique em Run, confirme "Success" antes de rodar o próximo.

Nota histórica: a primeira versão do `002` criava `staff_users` sem habilitar RLS — o próprio linter do SQL Editor pegou isso antes de rodar em produção. Corrigido com `alter table staff_users enable row level security;` logo após a criação da tabela. Se algum dia precisar recriar o projeto do zero, use a versão atual do arquivo (já com a correção).

## 3. Verificação pós-migration

Checklist rápido depois de rodar as 15 migrations (001 a 015):

- **Table Editor**: as 9 tabelas presentes (8 de negócio + `staff_users`), todas com RLS habilitado. `contracts` já com a coluna `prazo_indeterminado` (Migration 013).
- **Storage**: bucket `contracts` existe e está marcado como **Private**.
- **Database → Roles**: papéis `agente_ia` e `cron_batch` presentes.
- **Database → Functions**: `is_staff`, `agent_contract_id`, `set_updated_at`, as funções RPC de escrita do agente (`agent_update_charge_status`, `agent_open_maintenance_ticket`, `agent_create_escalation`, `agent_log_message`, `agent_registrar_alerta_renovacao`, `agent_registrar_calculo_reajuste`, `agent_aplicar_reajuste`, `agent_finalizar_contrato`), as de leitura em lote do `cron_batch` (`cron_listar_charges_ativas`, `cron_listar_contratos_ativos`, `cron_listar_clausulas_financeiras`, `cron_listar_reajustes_para_aplicar`), e `resolver_contrato_por_telefone` (papel `anon`) presentes.

## 4. Variáveis de ambiente (`.env`)

O `.env` nunca vai para o Git (já excluído no `.gitignore`). Copie `.env.example` para `.env` e preencha:

| Variável | Onde encontrar |
|---|---|
| `SUPABASE_URL` | `https://<Project ID>.supabase.co` |
| `SUPABASE_ANON_KEY` | Settings → API Keys → aba "Publishable and secret API keys" → **Publishable key** |
| `SUPABASE_SERVICE_ROLE_KEY` | Settings → API Keys → mesma aba → **Secret key** (clique no ícone de olho para revelar) |
| `SUPABASE_JWT_SECRET` | ver seção 5 abaixo |

Nota sobre nomenclatura: o Supabase migrou do modelo antigo de chaves (`anon`/`service_role`, JWT-based) para um novo modelo (`publishable`/`secret`). As legadas ainda funcionam mas serão descontinuadas até o fim de 2026 — por isso já usamos as novas desde o início do projeto. Mantivemos os nomes de variável antigos (`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`) por compatibilidade com o `.env.example` original; o valor colado nelas é o das novas chaves.

## 5. Identidade do agente de IA (JWT assinado pelo backend)

**Decisão de arquitetura:** o agente de IA não faz login como um usuário Supabase Auth normal. Em vez disso, o próprio backend assina um JWT de curta duração por conversa, contendo:

```json
{
  "role": "agente_ia",
  "contract_id": "<uuid do contrato>",
  "exp": <timestamp curto, ex: agora + alguns minutos>
}
```

Esse token é enviado no header `Authorization: Bearer <token>` nas chamadas à API do Supabase. A função `agent_contract_id()` (definida no `002_auth_rbac_rls.sql`) lê o claim `contract_id` desse token para aplicar o isolamento por contrato em todas as políticas de RLS.

**Por que não usar o Custom Access Token Hook do Supabase:** essa alternativa exigiria criar uma conta de login (Supabase Auth) por contrato só para o agente, além de depender de um recurso ainda em Beta. Assinar o token diretamente no backend é mais simples, documentado oficialmente pelo Supabase para esse tipo de cenário, e não exige nenhuma mudança no SQL já escrito.

**Configuração necessária:** o projeto nasce com uma chave de assinatura assimétrica (ECC/P-256) como padrão — a chave privada fica só com o Supabase, não é possível extrair. Para o backend poder assinar seus próprios tokens, foi criada uma **Standby Key adicional, tipo HS256 (Shared Secret), com segredo importado** (gerado localmente, não pelo Supabase) em Settings → JWT Keys → JWT Signing Keys → "Create a new Standby Key" → marcar "Import an existing secret". O valor desse segredo vai em `SUPABASE_JWT_SECRET` no `.env` — **nunca compartilhar esse valor fora do `.env` local**.

Essa chave HS256 fica como standby (nunca precisa virar "current") — ela só serve para validar os tokens que o backend assina, não interfere no login normal de humanos (staff), que continua usando a chave ECC.

**Pendente:** implementar, no código do backend (`app/orchestrator/` ou `app/tools/`), a função que efetivamente monta e assina esse JWT por conversa.

## 6. Usuários staff (Auth)

Cadastro em duas etapas:

1. **Authentication → Users → Add user**: cria o login (email + senha) para cada pessoa humana que vai acessar o Lovable (Domingos, Fernanda, etc.). Copie o **User UID** gerado.
2. **SQL Editor**: insira uma linha por pessoa na tabela `staff_users`, vinculando o UID ao papel:

```sql
insert into staff_users (user_id, nome, role) values
  ('<uuid>', '<nome>', '<gestora | owner | customer_success>');
```

**Status:** pendente — aguardando levantamento de quem precisa de acesso e qual papel cada um deve ter.

## Pendências gerais

- Cadastro dos usuários staff (seção 6).
- Implementação da assinatura do JWT do agente no código do backend (seção 5).
- Variáveis de ambiente do WhatsApp Business API, Anthropic e Redis — pendentes até essas contas existirem.
- Deletar o projeto Supabase criado inicialmente na região errada (Oregon/`us-west-2`), se ainda não foi feito.
