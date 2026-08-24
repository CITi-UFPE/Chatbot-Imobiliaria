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
tipo aluguel e conta) — transporte a conectar na WA-08/WA-05. O texto livre
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
livre validado com o cliente. Transporte a conectar na WA-08/WA-05.

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

**Exemplo:** `João`, `Apto 302, Ed. X`, `R$ 1.500,00`, `15/09/2026`,
`1.500,00`

**Consumidor:** `app/agents/a2_cobranca/notificacao.py::notificar_fernanda_comprovante`
— transporte a conectar na WA-05/WA-06. **Observação em aberto:** o texto
livre atual também aceita uma `nota_deteccao_automatica` opcional (só
aparece quando o sistema resolveu sozinho entre múltiplas charges em
aberto) — como um template Meta tem número FIXO de variáveis, essa nota
não está representada aqui. Quem implementar a WA-06 precisa decidir: (a)
omitir a nota na versão via template, ou (b) sempre incluir uma 6ª
variável vazia quando não houver nota.

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

**Botões (quick reply):** "Cobre os dois" / "Só uma delas" / "Valor
diverge" — payload dinâmico via `montar_button_id_combinado_todos` (as
duas outras ações não têm suporte de decodificação formal ainda, ver
`button_ids.py`; "Só uma delas" é tratado com cautela na WA-06, nunca
altera charge automaticamente).

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
— transporte a conectar na WA-05/WA-06.

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
(chama `notificar_staff`, `app/agents/a5_escalonamento/notificacao.py`) —
transporte a conectar na WA-05. Mesma dúvida de destino da
`alerta_contratual`: hoje não existe uma variável de ambiente pro telefone
de staff usada por `notificar_staff` — recomenda-se reaproveitar
`WHATSAPP_STAFF_PHONE_NUMBER` (introduzida nesta WA-09) em vez de criar uma
segunda variável equivalente.

---

## Resumo — variável de ambiente de destino por template

| Template | Destinatário | Variável de ambiente |
|---|---|---|
| `aviso_vencimento`, `aviso_atraso`, `aviso_atraso_severo` | Inquilino | `contrato.telefone_whatsapp` (não é uma env var — vem do registro do contrato) |
| `comprovante_para_conferencia`, `pagamento_combinado` | Fernanda (staff) | a definir na WA-05/WA-06 — sugestão: reaproveitar `WHATSAPP_STAFF_PHONE_NUMBER` |
| `alerta_contratual` | Equipe (Domingos/Fernanda) | `WHATSAPP_STAFF_PHONE_NUMBER` |
| `escalonamento_equipe` | Equipe | a definir na WA-05 — sugestão: reaproveitar `WHATSAPP_STAFF_PHONE_NUMBER` |
