# Homologação integrada — WhatsApp Cloud API (staging)

WA-10 — Projeto Domingos Monteiro.

**O que este documento é:** o procedimento pra validar, num ambiente de
staging separado de produção, que as WA-01 a WA-09 funcionam de ponta a
ponta com transporte real (Meta Cloud API + Supabase de teste). **O que
este documento NÃO é:** uma confirmação de que a homologação já foi
executada. Nenhuma linha da seção 7 (Evidências) foi preenchida por esta
task — o ambiente onde esta task rodou não tem credenciais reais da Meta,
Railway nem Supabase de staging, então nenhum cenário da matriz foi
executado de verdade. Passos que dependem de painel da Meta, Railway ou
Supabase estão marcados **[EXECUÇÃO HUMANA]** — só quem tem acesso a essas
contas pode rodá-los.

---

## 1. Variáveis necessárias (sem valores secretos)

Todas vêm de `.env.example`; nenhum valor real aparece neste documento nem
deve aparecer em nenhum log, commit ou mensagem.

| Variável | Obrigatória p/ homologação | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sim | A1/A3/A5 (classificação, extração de comprovante) chamam a Claude de verdade. |
| `SUPABASE_URL` | Sim | Projeto Supabase de **staging**, nunca o de produção. |
| `SUPABASE_SERVICE_ROLE_KEY` | Sim | Usada só pela camada de auth do backend pra assinar o JWT escopado por contrato (nunca exposta a um cliente). |
| `SUPABASE_ANON_KEY` | Sim | Resolução de contrato por telefone (`resolver_contrato_por_telefone`, papel `anon`). |
| `SUPABASE_JWT_SECRET` | Sim | Segredo da Standby Key HS256 do projeto de staging — nunca o de produção. |
| `WHATSAPP_PHONE_NUMBER_ID` | Sim | Número de teste cadastrado no Business Manager. |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Sim | WABA de teste. |
| `WHATSAPP_ACCESS_TOKEN` | Sim | Token de acesso do número de teste. |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Sim | String arbitrária escolhida por quem configura — só precisa bater entre o painel da Meta e esta variável. |
| `WHATSAPP_APP_SECRET` | Sim (obrigatório antes de qualquer teste de POST real) | Valida a assinatura `X-Hub-Signature-256` — sem isso, o webhook aceita POST de qualquer origem. |
| `WHATSAPP_ENVIO_ATIVO` | Sim — controla a homologação | Kill switch. Ver seção 8. |
| `WHATSAPP_GRAPH_API_VERSION` | Não (tem padrão `v21.0`) | Fixar mesmo assim, pra homologação não depender do padrão interno. |
| `WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB` | Não (padrão 10) | Relevante pro cenário 10 da matriz (mídia grande demais). |
| `WHATSAPP_STAFF_PHONE_NUMBER` | Sim | Telefone/E.164 que recebe `alerta_contratual`, `escalonamento_equipe`, `manutencao_equipe` e as DMs de comprovante do A2 — precisa ser um celular de teste autorizado no número de teste (ver Trilha administrativa). |
| `REDIS_URL` | Não | Fora do escopo desta sprint (dedup entre instâncias) — não usado por nenhum caminho testado aqui. |
| `ENVIRONMENT` | Sim — deve ser `staging` ou qualquer valor ≠ `production` | Controla se o router `dev_chat` é incluído (`app/api/main.py`) — precisa continuar acessível em staging pros cenários que usam o chat simulado como atalho. |
| `TIMEZONE` | Não (padrão `America/Recife`) | Usado pelos crons pra calcular "hoje". |
| `CORS_ALLOW_ORIGINS` | Não | Só relevante se o painel web também for exercitado nesta homologação. |

**Nota à parte, fora do escopo desta correção:** `.env.test.example` ainda
comenta "rode as migrations 001..014" — desatualizado desde a Migration
020. Não é um dos 5 pontos do checkup do Daniel nem um bloqueador da WA-10,
só uma inconsistência de comentário que vale corrigir quando alguém mexer
nesse arquivo de novo.

---

## 2. Verificar o webhook — GET (handshake)

**[EXECUÇÃO HUMANA]** No painel da Meta (WhatsApp Manager → Configuration →
Webhook), configure a Callback URL (`https://<host-staging>/webhook/whatsapp`)
e o Verify Token (mesmo valor de `WHATSAPP_WEBHOOK_VERIFY_TOKEN`). A Meta
faz um GET automático ao salvar — confirma sozinha se bateu.

Pra testar manualmente antes ou depois (local ou contra o host de staging):

```bash
curl -i "https://<host-staging>/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=<WHATSAPP_WEBHOOK_VERIFY_TOKEN>&hub.challenge=12345"
```

Esperado: `200` com corpo `12345` (eco exato do challenge — ver
`app/api/routers/whatsapp.py::verificar_webhook`). Token errado ou
`hub.mode` diferente de `subscribe` → `403`, sem eco do challenge.

---

## 3. Verificar o webhook — POST assinado

Pré-requisito: `WHATSAPP_APP_SECRET` configurado (sem ele, a verificação de
assinatura é pulada — ver `_assinatura_valida`, que loga um aviso explícito
e aceita qualquer POST; **não é um estado válido pra homologação**, só pra
dev local antes de ter o App Secret).

Gera a assinatura localmente (nunca cole o `WHATSAPP_APP_SECRET` real num
terminal compartilhado ou script versionado — rode isto interativamente):

```bash
python3 - <<'PY'
import hashlib, hmac, json

segredo = input("WHATSAPP_APP_SECRET (não será exibido em log nenhum): ").strip()
corpo = json.dumps({
    "entry": [{"changes": [{"value": {"messages": [{
        "id": "wamid.homologacao-teste-001",
        "from": "5581999990000",
        "type": "text",
        "text": {"body": "teste de homologação"},
    }]}}]}]
}).encode()

assinatura = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
with open("/tmp/payload_homologacao.json", "wb") as f:
    f.write(corpo)
print(f"\nX-Hub-Signature-256: sha256={assinatura}")
print("Payload salvo em /tmp/payload_homologacao.json")
PY
```

Depois:

```bash
curl -i -X POST "https://<host-staging>/webhook/whatsapp" \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=<valor impresso acima>" \
  --data-binary @/tmp/payload_homologacao.json
```

Esperado: `{"status": "recebido"}` (a mensagem entra em `BackgroundTasks`;
o telefone `5581999990000` não existe em nenhum contrato de teste, então o
processamento real vai cair no cenário 9 da matriz — resposta segura de
"nenhum contrato encontrado"). Reenviar o **mesmo** `id` de mensagem depois
deve devolver `{"status": "ja_processado"}` (dedup em memória, ver
`_mensagens_processadas`). Assinatura errada (mude 1 caractere do hex) deve
devolver `{"status": "assinatura_invalida"}`.

Apague `/tmp/payload_homologacao.json` depois do teste.

---

## 4. Matriz mínima — 12 cenários

Cada cenário: pré-condição, como executar, o que verificar (resposta +
efeito no banco), e o que registrar na seção 7. Cenários marcados **[REAL]**
exigem transporte de verdade (kill switch ligado, número de teste, celular
autorizado) — não dá pra validar só com o `dev_chat`. Cenários **[LOCAL]**
podem ser validados via `/dev/chat-simulado` sem depender da Meta.

| # | Cenário | Execução | Verificação |
|---|---|---|---|
| 1 | A1 responde pergunta contratual | **[LOCAL ou REAL]** Mandar uma pergunta sobre cláusula/valor pro contrato de teste. | Resposta contextual do A1; linha em `conversation_logs` (remetente `inquilino` e `agente`, `p_agente_responsavel='A1'`). |
| 2 | A3 abre manutenção e retorna protocolo | **[LOCAL ou REAL]** Relatar um problema (ex: "vazamento no banheiro"), confirmar imóvel quando perguntado. | Resposta contém protocolo `MNT-...`; linha nova em `maintenance_tickets`; equipe recebe template `manutencao_equipe` (staff, ver seção 1). |
| 3 | A2 baixa imagem real e processa comprovante | **[REAL]** — precisa ser mensagem de imagem/PDF de verdade vinda do WhatsApp (o `dev_chat` usa `_dados_base64`, que pula o download real — não exercita `whatsapp_client.baixar_midia`). Mandar uma foto de comprovante pro número de teste. | `charges.status` muda pra `aguardando_confirmacao`, `valor_identificado`/`data_identificada_comprovante` preenchidos; Fernanda recebe DM com botões (`comprovante_para_conferencia` ou variante). |
| 4 | Fernanda confirma pelo botão e a charge muda para `confirmado` | **[REAL]** Clicar "Confirmar" na DM do cenário 3. | `charges.status='confirmado'`, `data_pagamento` preenchida; inquilino recebe confirmação (`pagamento_confirmado`). |
| 5 | Valor divergente segue o fluxo previsto | **[REAL]** Repetir cenário 3, clicar "Valor diverge". | `charges.status='divergente'`; **nenhuma** notificação ao grupo/staff é disparada (fica só registrado, resolução manual — ver `marcar_valor_divergente`). |
| 6 | Cron envia D-5, D0, D+5, D+10 e D+15 por template | **[LOCAL]** Rodar `scripts/testar_cron_com_data.py` (ou o cron real) contra uma charge de teste com vencimento manipulado pra cada estágio. | `enviar_template` chamado com o template certo por estágio (`aviso_vencimento`/`aviso_atraso`/`aviso_atraso_severo`); com kill switch ligado, mensagem chega no celular de teste do inquilino. |
| 7 | A4 envia alerta contratual | **[LOCAL]** Rodar `scripts/rodar_a4_gestao_contratual.py` contra um contrato de teste com `data_termino` ou aniversário de reajuste caindo na janela D-60/D-30. | Staff recebe template `alerta_contratual` com o corpo formatado por `montar_alerta_renovacao`/`montar_calculo_reajuste`; `contract_alerts` registrado. |
| 8 | A5 escala e notifica equipe | **[LOCAL ou REAL]** Forçar um motivo de escalonamento (ex: pedir falar com humano, ou 2 tentativas falhas de identificação no A3). | Protocolo `ESC-...` retornado; staff recebe template `escalonamento_equipe` com protocolo/motivo/descrição. |
| 9 | Telefone desconhecido recebe resposta segura | **[REAL]** Mandar mensagem de um número **não cadastrado** em nenhum contrato de teste. | Resposta genérica ("Nenhum contrato ativo encontrado..."), sem vazar detalhe interno (`contract_id`, stack trace); nenhum erro 500 no log da aplicação. |
| 10 | Mídia inválida ou grande demais falha de modo controlado | **[REAL]** Mandar um arquivo com MIME não permitido (ex: `.zip`) ou maior que `WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB`. | Resposta de fallback controlado ao inquilino; nenhuma `charge` é criada/alterada; nenhuma exceção não tratada no log. |
| 11 | Janela aberta usa texto reativo; janela fechada usa template | **[REAL]** Responder dentro de 24h de uma mensagem do inquilino (texto livre esperado) e depois simular/aguardar janela fechada (template `retomada_atendimento` esperado). | Confirmar via log/captura qual dos dois caminhos `decidir_saida_para_contrato` (`app/tools/whatsapp_message_policy.py`) escolheu em cada caso. |
| 12 | Kill switch impede envios sem derrubar processamento e crons | **[LOCAL]** Repetir qualquer cenário acima com `WHATSAPP_ENVIO_ATIVO=false`. | `ResultadoEnvio.simulado=True`, nenhuma chamada HTTP real (conferir log "simulado=True"); o processamento e a gravação no banco continuam normais (ex: `maintenance_tickets`/`charges` são criados/atualizados igual). |

---

## 5. Comandos locais seguros

```powershell
# Suíte unitária completa — não precisa de nenhuma credencial real.
pytest tests -m "not integration" -q

# Testes de integração — só rodam de verdade com .env.test preenchido
# apontando pro Supabase de TESTE (ver tests/integration/README.md);
# sem isso, a suíte inteira é pulada (skip), não falha.
pytest -m integration -q

# Confere que nenhum arquivo ficou com marcador de conflito de merge
# nem problema de fim de linha misto antes de commitar.
git diff --check

# Confirma o que está staged/modified antes de qualquer commit.
git status --short
```

Resultado obtido nesta execução (ambiente sem `.env.test`, portanto sem
credenciais de Supabase/Meta de staging):

```
344 passed, 28 deselected (integração) — pytest tests -m "not integration" -q
344 passed, 28 skipped — pytest -q (suíte inteira, integração pulada por falta de .env.test)
```

`pytest -m integration -q` **não foi executado com credenciais reais** neste
ambiente — quem rodar a homologação de verdade precisa repetir este comando
com `.env.test` apontando pro Supabase de staging (seção 1) e colar o
resultado real na seção 7.

---

## 6. Checklist de inspeção do Supabase (depois de cada cenário)

- [ ] `contracts`: nenhuma linha de **produção** foi tocada — confirmar pelo projeto (URL do Supabase de staging, nunca o de produção) antes de olhar qualquer dado.
- [ ] `charges`: status bate com o esperado do cenário; `valor_identificado`/`data_identificada_comprovante` só preenchidos quando um comprovante real foi processado (cenários 3-5).
- [ ] `maintenance_tickets`: protocolo gerado, `categoria`/`urgencia` condizentes com o relato de teste (cenário 2).
- [ ] `escalations`: protocolo, motivo e descrição gravados (cenário 8).
- [ ] `contract_alerts`: alerta de renovação/reajuste registrado só uma vez por janela (cenário 7) — não duplicado por reexecução do cron.
- [ ] `conversation_logs`: uma linha por mensagem em cada sentido (inquilino/agente), sem lacunas.
- [ ] `agent_conversation_states`: vazio para qualquer contrato cujo fluxo (ex: A3) tenha chegado a "finalizado" — estado não deve "vazar" entre conversas.
- [ ] Nenhuma tabela contém telefone, nome ou contrato reais de produção — só os fixtures de teste usados na homologação.

---

## 7. Evidências

**Nenhuma linha desta tabela foi preenchida por esta task** — esta execução
não teve acesso a credenciais reais de Meta/Supabase de staging. Quem
executar a homologação de verdade preenche uma linha por cenário,
mascarando o telefone (últimos 4 dígitos visíveis, mesmo padrão de
`whatsapp_client.mascarar_telefone`) e sem colar nenhum token/segredo aqui.

| Data/hora | Executor | Cenário (nº da matriz) | Telefone mascarado | Resultado | `message_id` | Observação |
|---|---|---|---|---|---|---|
| | | | | | | |

---

## 8. Procedimento do kill switch

- **Padrão: desligado** (`WHATSAPP_ENVIO_ATIVO` ausente ou qualquer valor fora de `1/true/yes/on`, case-insensitive — ver `whatsapp_client.envio_ativo`). Nesse estado, nenhuma função de envio faz chamada HTTP real; todas devolvem `ResultadoEnvio(simulado=True)`. `baixar_midia` **não** respeita o kill switch (é leitura, não envio — decisão documentada em `whatsapp_client.py`).
- **Ligar pra homologação:** `WHATSAPP_ENVIO_ATIVO=true` **[EXECUÇÃO HUMANA — Railway]**, confirmando que `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_ACCESS_TOKEN` também estão configurados (sem eles, `validar_configuracao_envio_real` levanta `WhatsAppConfigError` listando pelo nome o que falta — nunca lista valores).
- **Confirmar que está realmente ligado antes de rodar qualquer cenário [REAL]:** rodar o cenário 12 primeiro (kill switch desligado) e comparar o comportamento — se `simulado=True` não aparecer no log depois de ligar a variável, a configuração não tomou efeito (verificar se o serviço foi reiniciado/redeployado após mudar a variável).
- **Desligar depois da homologação:** `WHATSAPP_ENVIO_ATIVO=false` (ou remover a variável) **[EXECUÇÃO HUMANA — Railway]** — sempre antes de qualquer merge/deploy que não seja especificamente pra rodar homologação real, pra nunca deixar staging enviando mensagens reais por padrão.

---

## 9. Procedimento de rollback de configuração (sem apagar dados)

Este rollback é só de **configuração** (variáveis de ambiente, webhook) —
em nenhum passo aqui se apaga contrato, charge, ticket, escalonamento ou
qualquer outra linha do banco.

1. **Primeiro passo, sempre:** `WHATSAPP_ENVIO_ATIVO=false` **[EXECUÇÃO HUMANA — Railway]** — para qualquer envio real imediatamente, sem precisar reverter mais nada primeiro.
2. Reverter as demais variáveis de ambiente (`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_STAFF_PHONE_NUMBER`) pro valor anterior à homologação **[EXECUÇÃO HUMANA — Railway]** — guarde os valores anteriores fora do Git (gerenciador de secrets ou o histórico de variáveis do próprio Railway) antes de trocar qualquer um, pra ter pra onde voltar.
3. Se a Callback URL ou o Verify Token do webhook foram alterados no painel da Meta pra apontar pro ambiente de staging, reverter pro valor de produção (ou deixar vazio, se staging nunca teve webhook configurado antes) **[EXECUÇÃO HUMANA — painel da Meta]**.
4. **Não** deletar em lote nenhuma linha criada durante a homologação. Se precisar limpar dados de teste especificamente, usar o mesmo padrão de `tests/integration/fixtures/contratos.py` (cada fixture apaga só o que ela mesma criou, via `on delete cascade` a partir de `contracts`) — nunca um `delete` sem filtro. A seção 7 (evidências, com telefone mascarado e timestamp) é a referência pra identificar exatamente quais registros pertencem à homologação, caso a limpeza seja necessária.
5. Se algum template novo (`manutencao_equipe`, ou qualquer outro ainda não aprovado) foi submetido à Meta só pra teste desta homologação, não tem como "desfazer" a submissão — a Meta não oferece remoção imediata. Se o template não deve continuar em uso, o suficiente é não referenciá-lo mais no código (kill switch desligado já impede qualquer envio, real ou de template rejeitado).
