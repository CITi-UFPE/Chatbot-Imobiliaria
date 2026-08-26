# Templates para cadastro e validação na Meta

Este é o documento operacional para cadastrar os templates usados pelo projeto
no **WhatsApp Manager → Modelos de mensagem**.

Não presuma que um template está aprovado só porque aparece neste arquivo. O
status precisa ser conferido no painel da Meta depois da submissão.

## Configuração comum a todos

- Categoria: **Utility**
- Idioma: **Português (Brasil) — `pt_BR`**
- Cabeçalho: nenhum
- Rodapé: nenhum
- Mídia: nenhuma
- Nomes: copiar exatamente, em minúsculas e com `_`
- Variáveis: manter a numeração e a ordem indicadas
- Bordas do corpo: nunca começar nem terminar o template com uma variável
- Botões: adicionar somente nos dois templates que possuem a seção “Botões”

Os textos são transacionais e não contêm oferta ou conteúdo promocional. A
Meta pode aprovar, rejeitar, pausar ou recategorizar um template; o código não
substitui essa decisão externa.

## Ordem recomendada de cadastro

1. Cadastre o nome, a categoria e o idioma.
2. Cole somente o conteúdo do bloco **Corpo**.
3. Informe os exemplos na ordem de `{{1}}` até a última variável.
4. Nos templates interativos, adicione os botões quick reply na ordem exata.
5. Revise a prévia e submeta para análise.
6. Registre no checklist final o ID/status devolvido pela Meta.

---

## 1. `aviso_vencimento`

**Corpo:**

```text
Olá, {{1}}! Passando para lembrar que {{2}} vence dia {{3}}. Qualquer dúvida, é só chamar por aqui.
```

**Variáveis, na ordem:**

1. Nome do inquilino — exemplo: `João Pereira`
2. Descrição do débito — exemplo: `o aluguel do Apto 305, Ed. Girassol`
3. Data de vencimento em `dd/mm/aaaa` — exemplo: `20/08/2026`

**Botões:** nenhum.

---

## 2. `aviso_atraso`

**Corpo:**

```text
Olá, {{1}}. Não localizamos o pagamento de {{2}} (vencimento {{3}}). O débito está em aberto há {{4}} dias. Valor original: R$ {{5}}. Multa: R$ {{6}}. Juros: R$ {{7}}. Valor total atualizado: R$ {{8}}. Assim que fizer o pagamento, envie o comprovante por aqui.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Descrição do débito — `o aluguel do Apto 305, Ed. Girassol`
3. Data de vencimento em `dd/mm/aaaa` — `20/08/2026`
4. Dias de atraso — `5`
5. Valor original, sem `R$` — `1.500,00`
6. Multa, sem `R$` — `30,00`
7. Juros, sem `R$` — `2,50`
8. Total atualizado, sem `R$` — `1.532,50`

**Botões:** nenhum.

---

## 3. `aviso_atraso_severo`

**Corpo:**

```text
Olá, {{1}}. O débito de {{2}} (vencimento {{3}}) segue em aberto há {{4}} dias, sem que tenhamos recebido comprovante de pagamento. Valor atualizado: R$ {{5}}. Pedimos a regularização o quanto antes — a partir de agora, o caso também é acompanhado diretamente pela gestão do imóvel.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Descrição do débito — `o aluguel do Apto 305, Ed. Girassol`
3. Data de vencimento em `dd/mm/aaaa` — `20/08/2026`
4. Dias de atraso — `15`
5. Total atualizado, sem `R$` — `1.537,50`

**Botões:** nenhum.

---

## 4. `comprovante_para_conferencia`

**Corpo:**

```text
Novo comprovante recebido

Inquilino: {{1}}
Imóvel: {{2}}

Valor identificado: {{3}}
Data identificada: {{4}}
Valor esperado (contrato): R$ {{5}}
Critério da correspondência: {{6}}

Aguardando sua conferência.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Identificação do imóvel — `Apto 305, Ed. Girassol`
3. Valor identificado já com `R$`, ou `não legível` — `R$ 1.500,00`
4. Data extraída em ISO `aaaa-mm-dd`, ou `não legível` — `2026-08-20`
5. Valor esperado sem `R$` — `1.500,00`
6. Critério — `Correspondência identificada automaticamente pelo valor`

**Botões quick reply, nesta ordem:**

1. `Confirmar`
2. `Valor diverge`

O texto dos botões é fixo no template. Os payloads internos são dinâmicos e o
backend os envia em cada mensagem; eles não devem ser escritos no corpo.

---

## 5. `pagamento_combinado`

**Corpo:**

```text
Comprovante recebido — possível pagamento combinado

Inquilino: {{1}}
Imóvel: {{2}}

Valor identificado: {{3}}
Data identificada: {{4}}

Cobranças em aberto que juntas somam esse valor (R$ {{5}}):
{{6}}

Revise as cobranças e selecione uma opção abaixo.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Identificação do imóvel — `Apto 305, Ed. Girassol`
3. Valor identificado já com `R$`, ou `não legível` — `R$ 1.500,00`
4. Data extraída em ISO `aaaa-mm-dd`, ou `não legível` — `2026-08-20`
5. Soma sem `R$` — `1.500,00`
6. Lista de cobranças — exemplo abaixo

Exemplo de `{{6}}`:

```text
- Aluguel: R$ 1.200,00
- Água: R$ 300,00
```

**Botões quick reply, nesta ordem exata:**

1. `Cobre os dois`
2. `Água paga`
3. `Aluguel pago`

Este template é usado somente quando existem exatamente duas cobranças: uma
de água e uma de aluguel. A ordem dos botões precisa ser idêntica à ordem do
backend.

---

## 6. `pagamento_combinado_resolucao_manual`

**Corpo:**

```text
Comprovante recebido — resolução manual necessária

Inquilino: {{1}}
Imóvel: {{2}}
Valor identificado: {{3}}
Data identificada: {{4}}

Cobranças em aberto:
{{5}}

Não foi possível distinguir automaticamente a cobrança paga porque há mais de uma cobrança do mesmo tipo. Acesse a plataforma, localize a cobrança correta, informe a data e o valor pagos e marque-a como paga.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Identificação do imóvel — `Apto 305, Ed. Girassol`
3. Valor identificado já com `R$`, ou `não legível` — `R$ 2.400,00`
4. Data em `dd/mm/aaaa`, ou `não legível` — `20/08/2026`
5. Lista determinística das cobranças — exemplo abaixo

Exemplo de `{{5}}`:

```text
- Aluguel | vencimento 10/08/2026 | R$ 1.200,00 | ID charge-001
- Aluguel | vencimento 10/09/2026 | R$ 1.200,00 | ID charge-002
```

**Botões:** nenhum.

---

## 7. `comprovante_sem_correspondencia`

**Corpo:**

```text
Comprovante recebido — não foi possível identificar automaticamente a que se refere

Inquilino: {{1}}
Imóvel: {{2}}
Valor identificado: {{3}}
Data identificada: {{4}}

Cobranças em aberto no contrato:
{{5}}

O valor não bate com nenhuma delas nem com a soma — resolver manualmente.
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`
2. Identificação do imóvel — `Apto 305, Ed. Girassol`
3. Valor identificado já com `R$`, ou `não legível` — `R$ 950,00`
4. Data extraída em ISO `aaaa-mm-dd`, ou `não legível` — `2026-08-20`
5. Lista de cobranças abertas — exemplo abaixo

Exemplo de `{{5}}`:

```text
- Aluguel: R$ 1.200,00
- Água: R$ 300,00
```

**Botões:** nenhum.

Importante: não adicione `R$` antes de `{{3}}` no corpo. O backend já inclui
esse prefixo quando o valor é legível.

---

## 8. `pagamento_confirmado`

**Corpo:**

```text
Recebemos seu comprovante, {{1}}. Pagamento confirmado, obrigado!
```

**Variáveis, na ordem:**

1. Nome do inquilino — `João Pereira`

**Botões:** nenhum.

---

## 9. `retomada_atendimento`

**Corpo:**

```text
Recebemos sua mensagem. Responda a esta conversa para continuarmos o atendimento por aqui.
```

**Variáveis:** nenhuma.

**Botões:** nenhum.

---

## 10. `alerta_contratual`

**Corpo:**

```text
Alerta de gestão contratual — {{1}}

{{2}}

Revise as informações e prossiga com a ação necessária.
```

**Variáveis, na ordem:**

1. Tipo do alerta — `Reajuste de aluguel`
2. Corpo completo do alerta contratual — exemplo abaixo

Exemplo de `{{2}}`:

```text
@Domingos Monteiro @Fernanda Monteiro, segue o cálculo de reajuste do contrato do Apto 302, Ed. X (João Silva), com data de aniversário em 14/08/2026.

Índice aplicável (conforme cláusula 5.2): IGPM
Valor atual do aluguel: R$ 1.500,00
Percentual de reajuste: 3,18%
Novo valor sugerido: R$ 1.547,70
```

**Botões:** nenhum.

O valor de `{{1}}` é sempre `Renovação de contrato` ou `Reajuste de aluguel`.

---

## 11. `escalonamento_equipe`

**Corpo:**

```text
Novo caso escalado — protocolo {{1}}
Motivo: {{2}}
{{3}}

O caso aguarda acompanhamento da equipe.
```

**Variáveis, na ordem:**

1. Protocolo — `ESC-2026-00042`
2. Motivo — `pedido_humano`
3. Descrição — `Inquilino pediu atendimento humano após duas tentativas de esclarecimento.`

**Botões:** nenhum.

---

## 12. `manutencao_equipe`

**Corpo:**

```text
Novo chamado de manutenção — {{1}}
Imóvel: {{2}}
Categoria: {{3}}
Urgência: {{4}}
Descrição do inquilino: {{5}}

O chamado aguarda acompanhamento da equipe.
```

**Variáveis, na ordem:**

1. Protocolo — `MNT-2026-0001`
2. Endereço e unidade — `Rua X, 123, apto 302`
3. Categoria — `hidraulica`
4. Urgência — `alta`
5. Descrição — `Vazamento no banheiro`

**Botões:** nenhum.

---

## Checklist de submissão

Preencha depois de cada cadastro no painel:

| Template | Categoria enviada | Idioma | Botões | Status na Meta | Observação/ID |
|---|---|---|---:|---|---|
| `aviso_vencimento` | Utility | pt_BR | 0 | A confirmar | |
| `aviso_atraso` | Utility | pt_BR | 0 | A confirmar | |
| `aviso_atraso_severo` | Utility | pt_BR | 0 | A confirmar | |
| `comprovante_para_conferencia` | Utility | pt_BR | 2 | A confirmar | |
| `pagamento_combinado` | Utility | pt_BR | 3 | A confirmar | |
| `pagamento_combinado_resolucao_manual` | Utility | pt_BR | 0 | A confirmar | |
| `comprovante_sem_correspondencia` | Utility | pt_BR | 0 | A confirmar | |
| `pagamento_confirmado` | Utility | pt_BR | 0 | A confirmar | |
| `retomada_atendimento` | Utility | pt_BR | 0 | A confirmar | |
| `alerta_contratual` | Utility | pt_BR | 0 | A confirmar | |
| `escalonamento_equipe` | Utility | pt_BR | 0 | A confirmar | |
| `manutencao_equipe` | Utility | pt_BR | 0 | A confirmar | |

## Depois da aprovação

1. Confirme que o nome e o idioma aprovados são idênticos aos deste documento.
2. Confirme que a quantidade e a ordem das variáveis não foram alteradas.
3. Confirme os títulos e a ordem dos quick replies.
4. Não ative `WHATSAPP_ENVIO_ATIVO` em produção antes da homologação em staging.
5. Registre rejeições ou recategorizações no checklist; não altere o código
   silenciosamente para acomodar uma mudança feita apenas no painel.

## Referências da Meta

- [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)
- [Exemplo oficial de criação de template com quick replies na coleção da Meta](https://www.postman.com/meta/whatsapp-business-platform/request/uzphwqw/create-template-w-text-header-text-body-text-footer-and-2-quick-reply-buttons)
- [Curso Meta Blueprint sobre criação e envio de templates](https://www.facebookblueprint.com/student/path/253055-message-templates)
