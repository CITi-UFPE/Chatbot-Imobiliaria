# Catálogo de templates — WhatsApp Business (Meta Cloud API)

WA-09 — Projeto Domingos Monteiro.

**Status: nenhum destes templates foi submetido ou aprovado pela Meta.** Este
documento é o catálogo operacional pra copiar cada um pro painel do WhatsApp
Manager (Business Settings → Message templates) e submeter — não é uma
confirmação de aprovação. A submissão em si é atividade administrativa (ver
"Trilha administrativa paralela" no plano da sprint), fora do escopo de
código desta task. Depois de submetido, cada template pode levar até 24h
pra ser aprovado, rejeitado ou pedir ajuste pela Meta.

Todos os templates abaixo são categoria **Utility** (transacional — dados
sobre um pagamento, contrato ou atendimento já em andamento, nunca
promocional/marketing) e idioma **pt_BR**. Tom estritamente transacional em
todos: sem emojis, sem linguagem de venda, sem urgência artificial.

## Convenções deste documento

- **Ordem das variáveis**: a ordem abaixo é a que o código passa pro
  parâmetro `parametros` de `enviar_template` (`app/tools/whatsapp_client.py`)
  — trocar a ordem no painel da Meta sem atualizar o código (ou vice-versa)
  faz a mensagem sair com os dados nos campos errados, sem erro nenhum
  acusado em tempo de execução (a Meta só reclama se a CONTAGEM de
  variáveis não bater, nunca se a ordem semântica estiver trocada).
- **Exemplo**: obrigatório pra Meta aprovar — cada variável precisa de um
  valor de exemplo plausível no momento da submissão.
- **Consumidor**: arquivo/função no backend responsável por montar os
  parâmetros e chamar `enviar_template`.

---

## 1. `aviso_vencimento`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Olá, {{1}}! Passando para lembrar que {{2}} vence dia {{3}}. Qualquer dúvida, é só chamar por aqui.
```

**Variáveis:**
1. Nome do inquilino (tratamento — primeiro nome se PF, razão social se PJ)
2. Descrição do débito (ex: "o aluguel do Apto 302, Ed. X" ou "sua conta de água")
3. Data de vencimento (`dd/mm/aaaa`)

**Exemplo:** `João`, `o aluguel do Apto 302, Ed. X`, `15/09/2026`

**Consumidor:** `app/agents/a2_cobranca/mensagens.py` (estágios `d-5`/`d0`,
tipo aluguel e conta) — transporte integrado pela WA-08/WA-05. O texto livre
atual de `_montar_mensagem_aluguel`/`_montar_mensagem_conta` pra esses dois
estágios é mais informal ("Bom dia" vs "Olá") — este corpo generaliza os
dois casos num único template revisável pela Meta; ajustar o tom exato é
decisão de quem implementar a WA-08.

---

## 2. `aviso_atraso`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Olá, {{1}}. Não localizamos o pagamento de {{2}} (vencimento {{3}}). O débito está em aberto há {{4}} dias. Valor original: R$ {{5}}. Multa: R$ {{6}}. Juros: R$ {{7}}. Valor total atualizado: R$ {{8}}. Assim que fizer o pagamento, envie o comprovante por aqui.
```

**Variáveis:**
1. Nome do inquilino
2. Descrição do débito
3. Data de vencimento (`dd/mm/aaaa`)
4. Dias de atraso
5. Valor original (sem encargos)
6. Valor da multa
7. Valor dos juros
8. Valor total atualizado (original + multa + juros)

**Exemplo:** `João`, `o aluguel do Apto 302, Ed. X`, `15/09/2026`, `5`,
`1.500,00`, `15,00`, `2,50`, `1.517,50`

**Consumidor:** `app/agents/a2_cobranca/mensagens.py` (estágios `d+5`/`d+10`)
— valores vêm de `_calcular_encargos` (mesmo arquivo), já usados no texto
livre validado com o cliente. Transporte integrado pela WA-08/WA-05.

---

## 3. `aviso_atraso_severo`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
{{1}}, o débito de {{2}} (vencimento {{3}}) segue em aberto há {{4}} dias, sem que tenhamos recebido comprovante de pagamento. Valor atualizado: R$ {{5}}. Pedimos a regularização o quanto antes — a partir de agora, o caso também é acompanhado diretamente pela gestão do imóvel.
```

**Variáveis:**
1. Nome do inquilino
2. Descrição do débito
3. Data de vencimento (`dd/mm/aaaa`)
4. Dias de atraso
5. Valor total atualizado

**Exemplo:** `João`, `o aluguel do Apto 302, Ed. X`, `15/09/2026`, `15`,
`1.545,00`

**Consumidor:** `app/agents/a2_cobranca/mensagens.py` (estágio `d+15`) —
mesmo racional do `aviso_atraso`, versão mais grave (menciona
acompanhamento direto da gestão, igual ao texto livre atual). Transporte a
conectar na WA-08/WA-05.

---

## 4. `comprovante_para_conferencia`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Novo comprovante recebido

Inquilino: {{1}}
Imóvel: {{2}}

Valor identificado: {{3}}
Data identificada: {{4}}
Valor esperado (contrato): R$ {{5}}
Critério da correspondência: {{6}}
```

**Botões (quick reply):** "Confirmar" / "Valor diverge" — payload
dinâmico por envio, montado com `montar_button_id_confirmar`/
`montar_button_id_divergente` (`app/agents/a2_cobranca/button_ids.py`), pra
o clique ser reconhecido por `decodificar_button_id` no webhook.

**Variáveis:**
1. Nome do inquilino
2. Identificação do imóvel
3. Valor identificado no comprovante (ou "não legível")
4. Data identificada no comprovante (ou "não legível")
5. Valor esperado, conforme o contrato
6. Critério determinístico: `Única cobrança em aberto` ou
   `Correspondência identificada automaticamente pelo valor`

**Exemplo:** `João`, `Apto 302, Ed. X`, `R$ 1.500,00`, `15/09/2026`,
`1.500,00`, `Correspondência identificada automaticamente pelo valor`

**Consumidor:** `app/agents/a2_cobranca/notificacao.py::notificar_fernanda_comprovante`
— transporte por template com payloads quick reply dinâmicos integrado na
união da WA-06 com a WA-08.

---

## 5. `pagamento_combinado`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Comprovante recebido — possível pagamento combinado

Inquilino: {{1}}
Imóvel: {{2}}

Valor identificado: {{3}}
Data identificada: {{4}}

Charges em aberto que juntas somam esse valor (R$ {{5}}):
{{6}}
```

**Botões (quick reply), nesta ordem:** "Cobre os dois" / "Água paga" /
"Aluguel pago". O primeiro usa `montar_button_id_combinado_todos`; os dois
seguintes usam `montar_button_id_combinado_parcial`, com a cobrança indicada
como paga e a outra como restante. A ordem é fixa e deve ser idêntica no
WhatsApp Manager e no código.

Este template só é usado quando existem exatamente duas cobranças abertas:
uma de água e uma de aluguel. Tipos repetidos e conjuntos com três ou mais
cobranças usam `pagamento_combinado_resolucao_manual`, sem botões.

**Variáveis:**
1. Nome do inquilino
2. Identificação do imóvel
3. Valor identificado no comprovante
4. Data identificada no comprovante
5. Soma das charges em aberto que batem com o valor
6. Lista das charges em aberto (uma por linha, ex: "- Aluguel: R$ 1.200,00")

**Exemplo:** `João`, `Apto 302, Ed. X`, `R$ 1.500,00`, `15/09/2026`,
`1.500,00`, `- Aluguel: R$ 1.200,00\n- Água: R$ 300,00`

**Consumidor:** `app/agents/a2_cobranca/notificacao.py::notificar_fernanda_pagamento_combinado`
— transporte por template com payloads quick reply dinâmicos integrado na
união da WA-06 com a WA-08.

---

## 6. `alerta_contratual`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Alerta de gestão contratual — {{1}}

{{2}}
```

**Variáveis:**
1. Tipo do alerta — sempre um destes dois valores fixos, nunca texto livre
   arbitrário: `"Renovação de contrato"` ou `"Reajuste de aluguel"`
2. Corpo completo do alerta, já formatado por
   `montar_alerta_renovacao`/`montar_calculo_reajuste`
   (`app/tools/mensagens_gestao_contratual.py`) — inclui a menção
   `@Domingos Monteiro @Fernanda Monteiro` e todos os dados do caso
   (imóvel, inquilino, datas, valores)

**Exemplo:** `Reajuste de aluguel`, `@Domingos Monteiro @Fernanda Monteiro,
segue o cálculo de reajuste do contrato do Apto 302, Ed. X (João Silva),
com data de aniversário em 14/08/2026.\n\nÍndice aplicável (conforme
cláusula 5.2): IGPM\nValor atual do aluguel: R$ 1.500,00\nPercentual de
reajuste: 3,18%\nNovo valor sugerido: R$ 1.547,70`

**Consumidor:** `app/agents/a4_gestao_contratual/fluxo.py::_notificar_staff_alerta_contratual`
(implementado nesta WA-09). **Destinatário: `WHATSAPP_STAFF_PHONE_NUMBER`
— NÃO o telefone do inquilino.** O corpo já menciona os gestores pelo nome
e pede que eles tomem uma decisão; não é uma mensagem apropriada pro
inquilino ver.

**Observação:** a variável 2 é um bloco de texto mais longo e menos
rígido que os demais templates deste catálogo — times de revisão da Meta
às vezes pedem mais estrutura (variáveis separadas por campo) em vez de um
parágrafo inteiro num único parâmetro. Se a Meta rejeitar ou pedir ajuste,
a alternativa é quebrar a variável 2 em campos individuais (imóvel,
inquilino, datas, valores) — ver `montar_alerta_renovacao`/
`montar_calculo_reajuste` pra saber quais campos existem hoje.

---

## 7. `escalonamento_equipe`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Novo caso escalado — protocolo {{1}}
Motivo: {{2}}
{{3}}
```

**Variáveis:**
1. Protocolo gerado pelo banco (`agent_create_escalation`)
2. Motivo do escalonamento (`avaliacao.motivo`)
3. Descrição objetiva do que motivou o escalonamento (`avaliacao.descricao`)

**Exemplo:** `ESC-2026-0042`, `pedido_humano`, `Inquilino pediu falar com
uma pessoa depois de duas tentativas de esclarecimento sobre a cláusula de
rescisão.`

**Consumidor:** `app/agents/a5_escalonamento/escalonamento.py::executar_escalonamento`
(chama `notificar_staff_escalonamento`,
`app/agents/a5_escalonamento/notificacao.py`) — transporte conectado pela
WA-05 e parâmetros separados pela WA-08.

---

## 12. `manutencao_equipe`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Novo chamado de manutenção — {{1}}
Imóvel: {{2}}
Categoria: {{3}}
Urgência: {{4}}
Descrição do inquilino: {{5}}
```

**Variáveis:**
1. Protocolo do ticket (`ticket.protocolo`)
2. Imóvel — endereço e número/apto juntos (ex: `Rua X, 123, apto 302`)
3. Categoria (`ticket.categoria` — ex: `hidraulica`, `eletrica`)
4. Urgência (`ticket.urgencia` — `alta`/`media`/`baixa`)
5. Descrição do problema relatada pelo inquilino, como veio na conversa

**Exemplo:** `MNT-2026-0001`, `Rua X, 123, apto 302`, `hidraulica`, `alta`,
`Vazamento no banheiro`

**Consumidor:** `app/agents/a3_manutencao/atendimento.py` (chama
`notificar_staff_manutencao`, `app/agents/a5_escalonamento/notificacao.py`),
com os parâmetros montados por
`app/tools/mensagens_manutencao.py::montar_parametros_notificacao_gestora`.

**Origem — checkup pós-WA-06/WA-08 (Ponto 3):** antes desta correção, o A3
reutilizava o template `escalonamento_equipe` (3 variáveis:
protocolo/motivo/descrição) através do notificador genérico `notificar_staff`,
mas mandava só 1 parâmetro (uma mensagem de texto pronta) — divergência de
contagem que a Meta rejeitaria com envio real ativo, mesmo passando
despercebida nos testes unitários (que só checavam a lista recebida pelo
cliente Python, não a validação de template da Meta). `manutencao_equipe` é
um template próprio, com suas 5 variáveis; não reaproveita
`escalonamento_equipe`, que continua exclusivo do A5.

**Observação:** de propósito não inclui `sinais_risco`, o prazo de resposta
estimado nem a flag de `classificacao_incerta` como variáveis separadas —
ficam de fora da versão estruturada por ora, mesmo racional já registrado
pro template `alerta_contratual` (campos objetivos tendem a passar mais
fácil pela revisão da Meta do que um bloco de texto mais longo). O texto
livre completo (`montar_notificacao_gestora`, com todos esses dados)
continua existindo em `app/tools/mensagens_manutencao.py`, só não é mais o
que vai no envio real — quem revisar este template pode decidir depois se
algum desses campos merece virar uma 6ª variável.

**Status operacional:** consumido pelo código, mas sem cadastro, submissão
ou aprovação presumidos na Meta. A ativação real depende dessas etapas
externas (mesma ressalva dos templates 8–11).

---

## Resumo — variável de ambiente de destino por template

| Template | Destinatário | Variável de ambiente |
|---|---|---|
| `aviso_vencimento`, `aviso_atraso`, `aviso_atraso_severo` | Inquilino | `contrato.telefone_whatsapp` (não é uma env var — vem do registro do contrato) |
| `comprovante_para_conferencia`, `pagamento_combinado`, `comprovante_sem_correspondencia`, `pagamento_combinado_resolucao_manual` | Fernanda (staff) | `WHATSAPP_STAFF_PHONE_NUMBER` |
| `alerta_contratual` | Equipe (Domingos/Fernanda) | `WHATSAPP_STAFF_PHONE_NUMBER` |
| `escalonamento_equipe` | Equipe | `WHATSAPP_STAFF_PHONE_NUMBER` |
| `manutencao_equipe` | Equipe | `WHATSAPP_STAFF_PHONE_NUMBER` |
| `retomada_atendimento`, `pagamento_confirmado` | Inquilino | `contrato.telefone_whatsapp` |

---

## 8. `retomada_atendimento`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Recebemos sua mensagem. Responda a esta conversa para continuarmos o atendimento por aqui.
```

**Variáveis:** nenhuma.

**Consumidor:** `app/tools/whatsapp_message_policy.py` — fallback quando uma
resposta reativa não puder comprovar que a janela de 24 horas está aberta.
Quando o inquilino responder, o agente recalcula a resposta usando o histórico;
nenhuma resposta pendente é armazenada por esta task.

---

## 9. `pagamento_confirmado`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Recebemos seu comprovante, {{1}}. Pagamento confirmado, obrigado!
```

**Variáveis:**
1. Nome do inquilino.

**Exemplo:** `João Pereira`

**Consumidor:**
`app/agents/a2_cobranca/notificacao.py::responder_confirmacao_pagamento` —
usar quando a confirmação da Fernanda ocorrer com a janela do inquilino
fechada ou indeterminada. Integração concluída após a WA-06 disponibilizar o
contrato à política.

---

## 10. `comprovante_sem_correspondencia`

**Categoria:** Utility · **Idioma:** pt_BR

**Corpo sugerido:**
```
Comprovante recebido — não foi possível identificar automaticamente a que se refere

Inquilino: {{1}}
Imóvel: {{2}}
Valor identificado: R$ {{3}}
Data identificada: {{4}}

Charges em aberto no contrato:
{{5}}

O valor não bate com nenhuma delas nem com a soma — resolver manualmente.
```

**Variáveis:**
1. Nome do inquilino.
2. Identificação do imóvel.
3. Valor identificado ou `não legível`.
4. Data identificada ou `não legível`.
5. Lista determinística das charges em aberto.

**Consumidor:**
`app/agents/a2_cobranca/notificacao.py::notificar_fernanda_sem_match` —
envio gerencial por template e destino de staff configurado.

**Status operacional dos templates 8–10:** especificados no repositório, mas
o código não presume cadastro, submissão ou aprovação na Meta. Essas etapas
continuam externas.

---

## 11. `pagamento_combinado_resolucao_manual`

**Categoria:** Utility · **Idioma:** pt_BR · **Sem botões**

**Corpo sugerido:**
```
Comprovante recebido — resolução manual necessária

Inquilino: {{1}}
Imóvel: {{2}}
Valor identificado: {{3}}
Data identificada: {{4}}

Cobranças em aberto:
{{5}}

Não foi possível distinguir automaticamente a cobrança paga porque há mais de uma cobrança do mesmo tipo. Acesse a plataforma, localize a cobrança correta, informe a data e o valor pagos e marque-a como paga.
```

**Variáveis:**
1. Nome do inquilino.
2. Identificação do imóvel.
3. Valor identificado no comprovante, formatado como `R$ 1.500,00`, ou
   `não legível`.
4. Data identificada no comprovante, no formato `dd/mm/aaaa`, ou
   `não legível`.
5. Lista determinística das cobranças em aberto, ordenada por tipo,
   vencimento e ID. Cada linha deve conter tipo, vencimento, valor e ID da
   cobrança.

**Exemplo:** `João Pereira`, `Apto 302, Ed. X`, `R$ 1.500,00`,
`15/09/2026`,
`- Aluguel | vencimento 10/09/2026 | R$ 1.200,00 | ID charge-001\n- Aluguel | vencimento 10/10/2026 | R$ 1.200,00 | ID charge-002`

**Consumidor:**
`app/agents/a2_cobranca/notificacao.py::notificar_fernanda_pagamento_combinado_manual`.
Nesse caminho, nenhuma cobrança é marcada como
`aguardando_confirmacao`; a gestão resolve pela plataforma.

**Status operacional:** consumido pelo código, mas sem cadastro, submissão
ou aprovação presumidos na Meta. A ativação real depende dessas etapas
externas.
