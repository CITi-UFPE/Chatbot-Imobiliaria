# Agente de Manutenção — mapeamento de fluxo (A3)

Status: **implementado (feat/agente-manutencao-a3)** — núcleo determinístico completo (classificação,
abertura de ticket, notificação, confirmação) + fluxo conversacional (confirmação de identidade,
esclarecimento por baixa confiança). Não testado ainda contra o webhook real do WhatsApp, porque
esse webhook/orchestrator não existe nesta branch (ver "Limitações e pendências" abaixo).

## Arquitetura

- `app/models/maintenance.py` — `ClassificacaoManutencao` (categoria, urgência, sinais de risco,
  confiança por dimensão) e `TicketManutencao` (espelha `maintenance_tickets` + `protocolo`).
- `app/tools/maintenance_classification.py` — chama a Claude (`claude-sonnet-5`, tool use forçado)
  para classificar categoria + urgência; `_contem_sinal_emergencia_real` é uma rede de segurança
  determinística (palavras-chave gás/fumaça/incêndio/choque) que nunca confia só no LLM para a
  exceção de emergência real. `gerar_pergunta_esclarecimento` gera a pergunta de baixa confiança
  via LLM (específica ao relato, não um texto fixo).
- `app/tools/mensagens_manutencao.py` — builders de texto (notificação à gestora, confirmação ao
  inquilino). Só retornam a string — não enviam nada (ver decisão sobre canal, abaixo).
- `app/agents/a3_manutencao/fluxo.py` — máquina de estados (`processar_turno`): identificação →
  coleta de descrição → classificação → esclarecimento (se confiança < 0.7) → ticket → notificação →
  confirmação. Recebe `abrir_ticket_fn`/`criar_escalonamento_fn` como dependências injetadas — não
  fala com o Supabase diretamente, o que torna o fluxo inteiro testável sem mocks de rede.
- `app/tools/supabase_client.py` — chama as RPCs `agent_open_maintenance_ticket` e
  `agent_create_escalation` recebendo um `access_token` já pronto (ver "JWT do agente" abaixo).
- `docs/schemas/005_ticket_manutencao_protocolo.sql` — adiciona `protocolo`, `sinais_risco` e
  `classificacao_incerta` a `maintenance_tickets`, e estende `agent_open_maintenance_ticket` pra
  gerar/gravar esses campos.
- `tests/test_maintenance_classification.py`, `tests/test_a3_fluxo.py`, `tests/test_supabase_client.py`
  — 17 testes, sem custo de API (chamadas à Claude e ao Supabase mockadas).

## Decisões e limitações conhecidas

**Modelo:** `claude-sonnet-5`, mesmo usado em `contract_extraction.py` — classificação de texto
curto num enum pequeno não exige Opus, e Haiku tem menos margem em casos ambíguos (ex: "fiação
perto do chuveiro").

**JWT do agente é fora de escopo desta branch.** A assinatura do JWT escopado por `contract_id`
(`role: agente_ia`) é responsabilidade de `feat/jwt-webhook-a5`. `supabase_client.py` recebe o
`access_token` já pronto como parâmetro — quem for integrar as branches precisa injetar a função de
assinatura real no lugar de `access_token` como string solta.

**Migration numerada 005, não 004.** A branch `feat/jwt-webhook-a5` (Davi) já tem uma migration 004
própria (`004_protocolo_e_resolucao_contrato.sql`) que altera `agent_create_escalation` (retorno
passa de `uuid` para `text`, com protocolo `ESC-2026-NNNNN` gerado dentro da função). Esta branch
não toca em `agent_create_escalation` nem em `escalations` — só em `maintenance_tickets` — mas o
número 004 já estava reservado. Ao integrar as duas branches, `supabase_client.py::criar_escalonamento`
precisa ser revisado para tratar o retorno em texto (protocolo) em vez de descartar o retorno.

**Notificação à gestora é só texto, sem canal de envio.** O WhatsApp Business API ainda não está
configurado no projeto (mesma pendência documentada em `docs/setup-supabase.md`). A branch do A5 já
tem um estágio equivalente (`app/agents/a5_escalonamento/notificacao.py::notificar_staff`, hoje só
loga) — quando as duas branches forem integradas, vale considerar se `montar_notificacao_gestora`
(aqui) deveria alimentar aquele mesmo `notificar_staff`, em vez de manter dois pontos de "enviar
mensagem à equipe" no projeto.

**Identificação do inquilino é uma heurística simples de palavras-chave** (sim/confirmo/correto vs
não/errado), não deteção de intenção real. Resolução de `contract_id` a partir do telefone também
não é feita por este agente — assume-se que o chamador já resolveu o imóvel/contrato antes de
invocar `processar_turno` (mesmo padrão de `resolver_contrato_por_telefone` na branch do A5).

## Visão geral

**Escopo do agente:** classificar → registrar no Supabase → notificar a gestora → confirmar ao
inquilino. Ponto final.

Tudo que acontece depois (acompanhamento, mudança de status, resolução do problema, avaliação) é
responsabilidade de outro processo ou pessoa, fora do escopo deste agente.

```
Inquilino relata problema
   ↓
[1] Identificação do imóvel/inquilino
   ↓
[2] Coleta de dados mínimos (se faltar, pergunta)
   ↓
[3] Classificação (categoria + urgência)
   ↓
[4] Abertura do ticket no Supabase
   ↓
[5] Notificação à gestora
   ↓
[6] Confirmação ao inquilino (protocolo + prazo)
   ↓
FIM — agente encerra participação
```

## 1–2. Identificação e coleta de dados

Campos obrigatórios antes de classificar:

- `imovel_id` (endereço + apto — via cadastro pelo telefone, ou perguntado)
- `descricao_livre` (relato original do inquilino)

```
SE inquilino já identificado (telefone bate com cadastro):
    → confirma: "Confirmando: apto 302, Ed. X?"
SENÃO:
    → pergunta: "Pra abrir o chamado, me confirma o endereço/apto?"
```

Se não conseguir identificar após 2 tentativas → escala para atendimento humano.

## 3. Classificação (categoria + urgência)

**Categoria:** hidráulica | elétrica | pintura | estrutural | outros

**Urgência:**

| Nível | Critério | Exemplos |
|---|---|---|
| Alta | Risco à segurança ou ao imóvel | vazamento grande, fiação exposta, porta/fechadura quebrada |
| Média | Afeta uso, sem risco | chuveiro não esquenta, torneira pingando |
| Baixa | Estético | pintura descascando, rejunte |

Abordagem híbrida: regras/palavras-chave (rápido, determinístico) + LLM, que extrai sinais de
gravidade da descrição (ex: "alagou", "fumaça", "não fecha mais a porta") para decidir a urgência
dentro da categoria.

**Prompt (esqueleto):**

```
Relato: "{descricao_livre}"
Retorne JSON:
{
  "categoria": "hidraulica|eletrica|pintura|estrutural|outros",
  "urgencia": "alta|media|baixa",
  "sinais_risco": [...] ou [],
  "justificativa": "..."
}
Regra: urgência ALTA exige risco explícito de segurança/dano ao imóvel,
não apenas a categoria. Na dúvida, classifique como o nível mais alto plausível.
```

**Exceção de emergência real:** se `sinais_risco` incluir gás, fumaça, incêndio ou choque em
pessoa, o agente orienta o inquilino a acionar serviço de emergência (bombeiros/193) além de seguir
o fluxo com urgência alta.

## 4. Abertura do ticket no Supabase

O campo `status` é gravado como `'aberto'` no momento da criação, por padrão, e serve apenas para
registro e consulta posterior. O agente não lê, não monitora e não atualiza esse campo depois de
criar o ticket — mudanças de status são feitas por quem cuida da manutenção na interface de gestão,
sem envolver o agente nem gerar comunicação automática ao inquilino.

## 5. Notificação à gestora

```
🔧 Novo chamado de manutenção — {protocolo}

Imóvel: {endereço}, apto {numero}
Categoria: {categoria}
Urgência: {urgencia} {🔴 alta / 🟡 média / 🟢 baixa}
Descrição do inquilino: "{descricao_inquilino}"
Sinais de risco: {sinais_risco ou "nenhum"}
Prazo de resposta: {prazo ou "sem prazo — fila programada"}
```

Todas as mensagens são enviadas imediatamente para a gestora independente da urgência, porém
deixando claro o nível de urgência na mensagem para que a gestora fique ciente.

## 6. Confirmação ao inquilino — fim da atuação do agente

**Alta:**

> "Registrei seu chamado ({protocolo}) como urgente e já avisei a gestora agora. Você deve receber
> um retorno em até 1h. Se for risco imediato (gás, fumaça, choque), procure ajuda de emergência
> agora."

**Média e Baixa:**

> "Chamado {protocolo} aberto e encaminhado. Você deve receber um retorno em até 24h."

Após essa mensagem, o agente encerra sua participação no caso, sem monitorar SLA, sem ler ou
atualizar o status (atualizado automaticamente a partir das ações da gestora na interface de
gestão), sem coletar avaliações.

## Sugestão: verificação de confiança na classificação

O modelo de linguagem, além de classificar categoria e urgência, pode retornar também um grau de
confiança para cada uma (`categoria_confidence` e `urgencia_confidence`, de 0 a 1). Isso permite
tratar de forma diferente os casos em que o relato é claro dos casos em que é ambíguo, em vez de
aplicar a mesma classificação automática para os dois.

**Funcionamento proposto:**

```
SE categoria_confidence < 0.7 OU urgencia_confidence < 0.7:
    → agente faz uma pergunta objetiva e específica, mirando só no que gerou a dúvida
    → reclassifica com a resposta, sem abrir uma segunda rodada de pergunta
SE mesmo assim a confiança continuar baixa:
    → assume o nível mais conservador na urgência (nunca subestima)
    → registra o ticket com uma marcação de incerteza (ex: campo classificacao_incerta = true)
```

**Exemplo de relato claro:** "A torneira da cozinha está pingando direto" — categoria e urgência
ficam evidentes no texto, confiança alta, segue o fluxo normal sem perguntas extras.

**Exemplo de relato ambíguo:** "Tem um problema na fiação perto do chuveiro" — pode ser elétrica ou
hidráulica, e a urgência muda dependendo disso. Nesse caso o agente perguntaria algo como: "Isso é
a fiação/tomada com problema, ou tem água vazando perto da fiação?"

**Benefício prático:** o valor de 0.7 é um ponto de partida, ajustável com base nos primeiros
tickets reais. A marcação de incerteza no ticket aparece na notificação da gestora (ex: "⚠️
Classificação com incerteza — revisar"), sinalizando que aquele caso específico merece uma checagem
mais atenta da descrição original antes de qualquer decisão.

**Trade-off a considerar:** essa etapa adiciona uma pergunta extra em casos ambíguos, o que aumenta
levemente a fricção do atendimento — mas reduz o risco de classificar errado um chamado que, por
exemplo, deveria ter sido tratado como urgente.
