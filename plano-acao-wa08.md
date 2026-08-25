# Plano de ação — WA-08: janela de 24 horas e templates proativos

## 1. Objetivo deste documento

Este documento explica o que a WA-08 muda na plataforma, como o fluxo ficará
na prática, quais alterações técnicas serão necessárias e quais decisões ainda
precisam ser tomadas antes da implementação.

Este arquivo é somente um plano. Sua criação não implementa a regra, não
altera código Python ou SQL e não representa aprovação de nenhum template pela
Meta.

## 2. Resumo da alteração em linguagem de produto

Hoje existem caminhos que enviam ou pretendem enviar texto livre diretamente
pelo WhatsApp. Porém, a Meta diferencia dois tipos de envio:

- **Texto livre:** resposta normal escrita pelo sistema. Só pode ser usado
  dentro da janela de atendimento de 24 horas aberta pela última mensagem do
  inquilino.
- **Template:** mensagem com estrutura, nome, idioma e variáveis previamente
  cadastrados e aprovados pela Meta. É o formato usado para iniciar ou retomar
  uma conversa fora da janela e para mensagens proativas, como uma cobrança
  disparada pelo cron.

A WA-08 cria um único ponto de decisão para toda a plataforma. Antes de enviar
uma mensagem, o sistema informará se ela é reativa ou proativa e fornecerá as
duas representações necessárias: o texto livre e, quando aplicável, o template
seguro. A política central escolherá qual delas pode ser enviada.

Esse é o objetivo principal da task: criar uma camada central de segurança e
conformidade para decidir **quando usar texto livre e quando usar template**.
Ela não cria um novo fluxo de negócio para o usuário. As mudanças observáveis
mais importantes são:

- respostas imediatas continuam como texto livre;
- cobranças do cron deixam de depender de texto livre e passam a produzir
  templates estruturados;
- mensagens proativas e gerenciais usam template por definição;
- nenhum agente consegue liberar texto livre por uma interpretação própria da
  janela;
- falhas de histórico nunca liberam texto livre por acidente.

Portanto, a maior parte do valor da WA-08 é preventiva: centralizar uma regra
da Meta e evitar erros específicos, raros, mas capazes de bloquear o envio ou
deixar diferentes partes da plataforma com comportamentos incompatíveis.

Em termos simples:

```text
Sistema quer enviar uma mensagem
          |
          +-- É proativa? -------------------- sim --> usa template
          |
          +-- É resposta a uma mensagem? ----- sim --> consulta a última
                                                    mensagem do inquilino
                                                        |
                                                        +-- menos de 24h --> texto
                                                        +-- 24h ou mais ---> template
                                                        +-- não sei --------> template
```

Nenhum agente calculará a janela por conta própria. A2, A5 e o orquestrador
apenas declararão a intenção e os dados da mensagem; a regra ficará em um
módulo central.

## 3. O que muda na prática para cada fluxo

### 3.1. Resposta normal a uma mensagem do inquilino

Exemplo: às 10h o inquilino pergunta qual é a chave Pix e o A1 responde alguns
segundos depois.

Fluxo esperado:

1. O webhook recebe a mensagem.
2. O contrato é identificado pelo telefone.
3. A mensagem recebida é gravada em `conversation_logs` como mensagem do
   inquilino.
4. O agente produz a resposta.
5. A política consulta a data da última mensagem do inquilino para aquele
   contrato.
6. Como se passaram apenas alguns segundos, a janela está aberta.
7. A resposta é enviada como texto livre.

Resultado para o usuário: a conversa continua normalmente, sem transformar
uma resposta reativa em template sem necessidade.

### 3.2. Limite exato da janela

Se a última mensagem foi recebida às 10h de segunda-feira:

- até 09h59min59s de terça-feira, a janela ainda está aberta;
- às 10h de terça-feira, completaram-se 24 horas e a janela está fechada;
- depois das 10h, a janela continua fechada.

A comparação será feita entre instantes timezone-aware. O timestamp do banco é
`timestamptz`, será normalizado para UTC e nunca será comparado com um horário
local sem timezone.

Regra matemática:

```text
agora - última_mensagem < 24 horas  -> janela aberta
agora - última_mensagem >= 24 horas -> janela fechada
```

### 3.3. Cobrança automática do A2

Exemplo: o cron diário encontra um aluguel no estágio D+5.

Fluxo esperado:

1. O cron identifica a charge e o estágio.
2. O A2 deriva nome do inquilino, imóvel, vencimento, dias de atraso e valores
   diretamente de `ChargeAtiva` e `DadosCobrancaContrato`.
3. O A2 monta uma saída estruturada com o template `aviso_atraso`.
4. A política reconhece o envio como proativo.
5. O sistema envia o template sem tentar liberar texto livre pela existência
   de uma conversa recente.

Mesmo que o inquilino tenha falado com a plataforma cinco minutos antes, a
cobrança do cron continua sendo proativa e usa template. Isso torna o
comportamento previsível e atende ao critério explícito da task.

### 3.4. Falha ou ausência de histórico

Exemplo: o banco está temporariamente indisponível justamente quando o sistema
vai responder.

O sistema não pode concluir que a janela está aberta. Enviar texto livre nesse
caso seria apostar que a mensagem ainda é permitida. A política será
fail-closed:

1. A consulta falha, retorna vazio ou devolve timestamp inválido.
2. A política classifica a janela como indeterminada.
3. Texto livre é bloqueado.
4. O sistema usa o template de segurança fornecido pelo fluxo.
5. A falha é registrada em log, sem expor telefone completo ou credenciais.

A mesma regra vale para timestamp sem timezone ou para um timestamp futuro
incoerente: se não for possível provar que a janela está aberta, usa-se
template.

### 3.5. Escalonamento do A5 para a equipe

A mensagem do A5 é dirigida à equipe, não ao inquilino. Ela é uma notificação
proativa de sistema e não depende da janela da conversa do inquilino.

Fluxo esperado:

1. O A5 registra a escalação e recebe o protocolo.
2. Monta os parâmetros `protocolo`, `motivo` e `descrição`.
3. Envia o template `escalonamento_equipe` para
   `WHATSAPP_STAFF_PHONE_NUMBER`.

Não será feita uma consulta à última mensagem do inquilino para liberar texto
livre destinado à equipe.

## 4. Fallback reativo de segurança

### 4.1. Por que esse template é necessário

O sistema já possui templates catalogados para cobrança e escalonamento, mas
não existe um template genérico para o seguinte caso:

- o sistema produziu uma resposta reativa;
- a janela está fechada ou não pôde ser confirmada;
- portanto, a resposta não pode sair como texto livre.

Isso tende a ser raro no fluxo normal, porque a mensagem que acabou de chegar
abre a janela e é registrada antes da resposta. Ainda assim, pode acontecer
quando:

- a gravação ou consulta do histórico falha;
- um job de retry tenta entregar a resposta muito tempo depois;
- o processamento fica atrasado por mais de 24 horas;
- existe inconsistência nos timestamps;
- o contrato não pode ser resolvido e, por isso, não existe client escopado
  para consultar seu histórico.

O fallback para template é exigido pela task. O código consegue decidir que
deve usar um template, mas não pode inventar um nome que não exista no painel
da Meta. Por isso falta uma decisão de produto e operação: qual conteúdo será
cadastrado e submetido à aprovação.

### 4.2. Alternativas possíveis

#### Alternativa A — template fixo de retomada, recomendado

Nome sugerido: `retomada_atendimento`.

Corpo sugerido:

```text
Recebemos sua mensagem. Responda a esta conversa para continuarmos o atendimento por aqui.
```

Preferencialmente sem parâmetros, para também funcionar quando ainda não foi
possível identificar o contrato ou o nome do inquilino.

Vantagens:

- conteúdo pequeno, determinístico e mais simples de submeter à Meta;
- não permite que texto arbitrário seja inserido em um template;
- funciona como fallback mesmo com poucos dados disponíveis;
- abre uma nova oportunidade de resposta do inquilino e, após essa resposta,
  uma nova janela de 24 horas.

Limitação:

- a resposta original do agente não é entregue naquele primeiro envio;
- para uma experiência completa, seria necessário decidir se a resposta
  pendente será armazenada e enviada depois que o inquilino responder, ou se o
  agente recalculará a resposta no novo turno. Esse armazenamento não está
  pedido na WA-08 e deve ser tratado como evolução separada.

#### Alternativa B — template com a resposta completa como parâmetro

Nome possível: `resposta_atendimento`.

Corpo hipotético:

```text
Resposta sobre o seu atendimento:
{{1}}
```

Vantagem:

- entrega imediatamente o conteúdo que o agente já produziu.

Riscos:

- `{{1}}` seria praticamente um bloco de texto livre arbitrário;
- a Meta pode rejeitar o template ou exigir uma estrutura mais específica;
- torna mais difícil garantir tom, tamanho e finalidade Utility;
- aumenta o risco de um conteúdo inadequado ser usado fora da janela sob a
  aparência de template aprovado.

Por esses motivos, esta alternativa não é recomendada sem validação prévia com
quem administra a conta Meta.

#### Alternativa C — não enviar nada

É tecnicamente segura, mas não atende ao fallback solicitado pela WA-08 e pode
deixar o usuário sem retorno. Portanto, não deve ser a solução desta task.

### 4.3. Decisão final

Usar `retomada_atendimento`, sem parâmetros, como fallback seguro. O código
deve documentar seu nome e formato, mas manter explicitamente o status
“pendente de submissão/aprovação na Meta”. Implementar a referência ao template
não significa que ele já esteja disponível em produção.

Essa recomendação foi aprovada para o plano final.

Antes de ativar o envio real, alguém responsável pela conta Meta deverá:

1. confirmar o texto final;
2. cadastrar o template com idioma `pt_BR` e categoria adequada;
3. submetê-lo à Meta;
4. aguardar aprovação;
5. validar se o nome aprovado é exatamente o usado pelo código.

### 4.4. Inventário real dos templates

Os templates já descritos em `docs/whatsapp/templates-meta.md` são:

| Template | Uso | Situação no repositório |
|---|---|---|
| `aviso_vencimento` | A2 D-5/D0 | corpo e parâmetros documentados |
| `aviso_atraso` | A2 D+5/D+10 | corpo e parâmetros documentados |
| `aviso_atraso_severo` | A2 D+15 | corpo e parâmetros documentados |
| `comprovante_para_conferencia` | Fernanda confere comprovante | integrado como template com quick replies após a WA-06 |
| `pagamento_combinado` | Fernanda confere várias charges | integrado como template com quick replies após a WA-06 |
| `alerta_contratual` | renovação/reajuste para a equipe | documentado e já consumido pela WA-09 |
| `escalonamento_equipe` | A5 avisa a equipe | documentado, transporte depende da WA-05 |

Documentar um template não significa que ele foi cadastrado ou aprovado na
Meta. Essa confirmação continua sendo uma atividade externa.

Com a decisão de que mensagens para a gerência também serão sempre templates,
ainda será necessário acrescentar ao catálogo:

| Novo template | Por que é necessário | Estrutura sugerida |
|---|---|---|
| `retomada_atendimento` | fallback quando a janela não puder ser comprovada | texto fixo, sem parâmetros |
| `pagamento_confirmado` | confirmação ao inquilino pode ocorrer mais de 24h depois do envio do comprovante | nome do inquilino ou texto fixo |
| `comprovante_sem_correspondencia` | avisar a gerência quando o comprovante não corresponde a nenhuma charge | nome, imóvel, valor/data identificados e resumo das charges |

O trabalho dentro do repositório é definir esses corpos e a ordem dos
parâmetros no catálogo e fazer os consumidores enviarem a estrutura correta.
O cadastro, a submissão e a aprovação continuam sendo feitos na plataforma da
Meta.

A integração com a WA-06 ampliou `MensagemTemplate` e `enviar_template` para
transportar payloads quick reply dinâmicos. Assim,
`comprovante_para_conferencia` e `pagamento_combinado` deixaram de depender de
`enviar_botoes` na notificação inicial à gestão. O formato segue os componentes
de botão dos templates da Meta e mantém a ordem cadastrada no catálogo.

## 5. Situação verificada das dependências

A verificação inicial foi feita em `feat/template_texto_livre`. A integração
final foi realizada em `feat/integracao-wa06-wa08`, criada a partir da
`develop` que já continha a WA-06.

### 5.1. WA-04 — implementada

Confirmada pelos seguintes elementos:

- commit `a0a2b50` e merge `e198f8e`;
- `processar_mensagem_recebida(..., responder_via_whatsapp=True)` no webhook;
- `_enviar_resposta_se_necessario` em
  `app/orchestrator/processar_mensagem.py`;
- chamada que antes era direta a `enviar_texto`, agora integrada à política da WA-08;
- `tests/test_whatsapp_webhook_processing.py`.

Esse ponto de integração já usa a política central. O `dev_chat` continua com
`responder_via_whatsapp=False` e não faz envio externo.

### 5.2. WA-07 — implementada

Confirmada pelos seguintes elementos:

- commit `faef58c` e merge `9f94c83`;
- `app/orchestrator/phone_normalization.py`;
- uso de `gerar_candidatos_telefone_br` na resolução do contrato;
- migration `019_normalizacao_telefone.sql`;
- testes unitários e de integração de resolução de telefone.

A WA-07 não bloqueia mais a WA-08. Ela ajuda a garantir que a mensagem
recebida seja associada ao contrato correto antes da consulta da janela.

### 5.3. WA-05 — implementada e incorporada

A WA-05 foi integrada no commit de merge `6e9ba63`. A2 e A5 já usam o cliente
central do WhatsApp, o kill switch continua seguro e as falhas de transporte
não apagam efeitos de negócio concluídos. A WA-08 substituiu os formatos
provisórios da WA-05 nos fluxos estáveis:

- o cron A2 deixou de usar `cobranca_mensagem` com um parâmetro único;
- A5 passou a fornecer protocolo, motivo e descrição separadamente;
- respostas da WA-04 passam pela política de janela.

### 5.4. WA-06 — implementada e integrada

A WA-06 foi incorporada à `develop` no merge `56c9b86` e integrada à WA-08
na branch `feat/integracao-wa06-wa08`. A união preservou:

- montagem e decodificação dos IDs dos botões;
- roteamento dos cliques pelo webhook;
- confirmação individual, divergência e pagamento combinado;
- fallback conservador do pagamento parcial;
- política central de texto/template e consulta da janela.

As notificações iniciais à gestão agora usam templates com quick replies. A
confirmação enviada ao inquilino consulta a janela do contrato e usa
`pagamento_confirmado` quando texto livre não estiver autorizado.

A segunda etapa antiga de `Só uma delas` permanece provisoriamente como a
única exceção gerencial interativa livre. Sua substituição foi separada no
documento `plano-fluxo-botoes-comprovante.md` e depende de aprovação antes de
ser implementada.

## 6. Arquitetura técnica proposta

### 6.1. Modelo explícito de saída

Criar `app/tools/whatsapp_message_policy.py` com modelos equivalentes a:

```python
class MensagemTexto:
    tipo = "texto"
    texto: str

class MensagemTemplate:
    tipo = "template"
    nome: str
    idioma: str
    parametros: tuple[str, ...]
```

A implementação poderá usar Pydantic ou dataclasses, desde que a distinção seja
explícita e validável. Não será usado um dicionário solto em que o chamador
precise inferir o tipo por campos opcionais.

### 6.2. Funções da política central

O módulo deverá separar três responsabilidades:

1. `buscar_ultima_mensagem_inquilino(client)` consulta o banco.
2. Uma função pura calcula se a janela está aberta usando timestamps
   timezone-aware.
3. Uma função decide e envia `MensagemTexto` ou `MensagemTemplate` pelo
   `whatsapp_client`.

A função pura deverá aceitar `agora` opcional para que os testes congelem o
instante sem monkeypatch global de relógio.

### 6.3. RPC incremental

Como não existe uma RPC adequada, criar uma migration incremental mínima,
provavelmente `docs/schemas/020_whatsapp_janela_atendimento.sql`, com função
equivalente a:

```text
agent_get_last_tenant_message_at() -> timestamptz | null
```

Requisitos de segurança:

- não receber `contract_id` como parâmetro;
- obter o contrato exclusivamente de `agent_contract_id()`;
- filtrar `conversation_logs.remetente = 'inquilino'`;
- retornar `max(timestamp)`;
- manter RLS de `conversation_logs` sem criar acesso cross-contrato;
- revogar execução genérica e conceder somente ao papel necessário;
- definir `search_path` de forma explícita se usar `security definer`.

O índice existente `(contract_id, timestamp)` já ajuda essa consulta. A
migration deve permanecer mínima e não remodelar a tabela.

### 6.4. Integração no orquestrador

Em `app/orchestrator/processar_mensagem.py`, a WA-04 chama hoje
`enviar_texto(telefone, resposta)` diretamente. Esse ponto passará a chamar a
política com:

- natureza `reativa`;
- resposta livre produzida pelo agente;
- template seguro de fallback;
- client escopado do contrato, quando disponível.

Cliques administrativos da Fernanda continuarão excluídos desse mecanismo.
Eventos de status continuarão sem envio. O `dev_chat` continuará sem transporte
externo.

Para erros ocorridos antes da resolução do contrato, não será possível
consultar uma RPC escopada. Esses casos devem cair diretamente no template
estático de retomada, nunca em texto livre.

### 6.5. Integração no A2

Os textos validados em `app/agents/a2_cobranca/mensagens.py` não serão
reescritos. Será adicionada uma montagem estruturada paralela, derivada dos
mesmos modelos de domínio e do mesmo cálculo de encargos.

Mapeamento:

| Estágio A2 | Template |
|---|---|
| `d-5` | `aviso_vencimento` |
| `d0` | `aviso_vencimento` |
| `d+5` | `aviso_atraso` |
| `d+10` | `aviso_atraso` |
| `d+15` | `aviso_atraso_severo` |

Ordem dos parâmetros:

| Template | Parâmetros, na ordem cadastrada na Meta |
|---|---|
| `aviso_vencimento` | nome, descrição do débito, data de vencimento |
| `aviso_atraso` | nome, descrição, vencimento, dias, valor original, multa, juros, total |
| `aviso_atraso_severo` | nome, descrição, vencimento, dias, valor total |

Formatação determinística:

- datas: `dd/mm/aaaa`;
- dias: inteiro em base 10;
- valores: padrão brasileiro, por exemplo `1.500,00`;
- descrição do aluguel: derivada do imóvel;
- descrição de conta: derivada de `charge.tipo` e `ROTULOS_CONTA`.

O cron sempre fornecerá uma `MensagemTemplate`. Ele não consultará a janela
para tentar converter a cobrança em texto.

### 6.6. Integração no A5

Depois da WA-05, o A5 deverá fornecer dados estruturados, evitando remontar ou
parsear a string concatenada atual:

```text
template: escalonamento_equipe
idioma: pt_BR
parâmetros: [protocolo, motivo, descrição]
destino: WHATSAPP_STAFF_PHONE_NUMBER
```

Essa saída será marcada como proativa e seguirá direto para template.

## 7. Arquivos alterados na implementação

- `app/tools/whatsapp_message_policy.py` — novo módulo central;
- `docs/schemas/020_whatsapp_janela_atendimento.sql` — nova RPC;
- `docs/setup-supabase.md` — registrar a migration e a RPC;
- `app/orchestrator/processar_mensagem.py` — substituir envio direto da WA-04;
- `app/agents/a2_cobranca/mensagens.py` — montar parâmetros de template sem
  alterar os textos existentes;
- `app/agents/a2_cobranca/cobranca.py` — marcar cron como proativo;
- `app/agents/a2_cobranca/notificacao.py` — integrar cron, comprovantes,
  botões e confirmação à saída central;
- `app/agents/a5_escalonamento/notificacao.py` e possivelmente
  `escalonamento.py` — template estruturado da equipe;
- `docs/whatsapp/templates-meta.md` — adicionar o template de retomada e
  manter seu status de aprovação explícito;
- `tests/test_whatsapp_message_policy.py` — nova suíte solicitada.

## 8. Plano de implementação

### Etapa 0 — dependências

1. WA-05 incorporada.
2. Núcleo da WA-08 e fluxos estáveis implementados.
3. WA-06 incorporada e conflitos resolvidos.
4. Templates com quick replies e confirmação ao inquilino integrados.

### Etapa 1 — política e modelo

1. Criar os modelos explícitos de texto e template.
2. Implementar a decisão pura entre os dois formatos.
3. Implementar despacho central para `enviar_texto` e `enviar_template`.

### Etapa 2 — histórico e timezone

1. Criar a migration incremental.
2. Criar a função Python de consulta.
3. Normalizar timestamps para UTC.
4. Aplicar fallback para template em qualquer estado indeterminado.

### Etapa 3 — fluxos reativos

1. Integrar a política no ponto criado pela WA-04.
2. Preservar a separação entre webhook real e `dev_chat`.
3. Garantir que status e cliques administrativos não gerem resposta indevida.

### Etapa 4 — fluxos proativos

1. Implementar o mapeamento de todos os estágios A2.
2. Fazer o cron produzir somente templates.
3. Fazer A5 produzir `escalonamento_equipe` de forma estruturada.

### Etapa 5 — documentação operacional

1. Documentar `retomada_atendimento` no catálogo.
2. Documentar `pagamento_confirmado` e
   `comprovante_sem_correspondencia`.
3. Documentar e testar a compatibilidade dos botões da WA-06 com templates.
4. Marcar claramente que cadastro e aprovação na Meta são externos ao código.
5. Registrar a migration 020 no setup do Supabase.

### Etapa 6 — testes, somente depois da implementação

Criar `tests/test_whatsapp_message_policy.py` com relógio fixo e mocks de
banco/transporte.

Cobertura mínima:

- 23h59 permite texto reativo;
- exatamente 24h exige template;
- mais de 24h exige template;
- histórico ausente exige template;
- falha de banco exige template;
- timestamp sem timezone exige template;
- timestamp incoerente não libera texto;
- mensagem proativa sempre usa template e não depende da consulta;
- todos os estágios do A2 usam o nome correto;
- idioma e ordem dos parâmetros estão corretos;
- datas e moedas possuem formatação determinística;
- cron A2 chama template, nunca texto.

Depois das alterações, executar exatamente:

```bash
pytest tests/test_whatsapp_message_policy.py tests/test_a2_comprovante_cron.py -q
```

Observação: `tests/test_a2_comprovante_cron.py` é atualmente um roteiro manual
sem funções `test_*` coletadas pelo pytest. Por isso, o teste automático de que
o cron produz template deverá estar em `test_whatsapp_message_policy.py` ou em
um teste unitário adicional coletável.

## 9. Critérios de aceite traduzidos em resultados observáveis

| Cenário | Resultado esperado |
|---|---|
| Inquilino falou há 23h59 e sistema está respondendo | texto livre |
| Inquilino falou há exatamente 24h | template |
| Inquilino falou há mais de 24h | template |
| Não existe mensagem anterior | template |
| Banco falhou | template e log seguro |
| Cron A2 executou D-5/D0 | `aviso_vencimento` |
| Cron A2 executou D+5/D+10 | `aviso_atraso` |
| Cron A2 executou D+15 | `aviso_atraso_severo` |
| A5 notificou a equipe | `escalonamento_equipe` |
| `dev_chat` processou mensagem | nenhum envio externo |
| Clique administrativo chegou | nenhuma resposta enviada à Fernanda por engano |

## 10. Riscos e cuidados

- Não duplicar a política dentro de A2, A5 ou orquestrador.
- Não usar `datetime.now()` sem timezone nem `date.today()` para a janela.
- Não assumir que template documentado já está aprovado.
- Não mudar os textos validados do A2.
- Não marcar charge como notificada para compensar falha de transporte sem
  uma decisão explícita de idempotência/entrega.
- Não permitir que alterações futuras nos botões contornem a política.
- Não usar uma falha de consulta como justificativa para texto livre.
- Não aceitar parâmetros em ordem diferente da cadastrada na Meta.

## 11. Confiança da resolução

| Condição | Confiança |
|---|---:|
| Política pura, timezone e testes de limite | 95% |
| Mapeamento e parâmetros dos templates A2 | 90% |
| Integração reativa, considerando WA-04 já presente | 90% |
| Núcleo implementado após WA-05 | 95% |
| Integração final após revisão/merge da WA-06 | 95% |

O núcleo, cron A2, A5 e os caminhos finais de comprovante da WA-06 estão
cobertos. A única evolução separada é a substituição aprovada posteriormente
do fluxo `Só uma delas`, descrita em `plano-fluxo-botoes-comprovante.md`.

## 12. Decisões finais

### 12.1. Fallback da janela

Usar `retomada_atendimento`, sem parâmetros, quando a janela estiver fechada
ou não puder ser determinada e não houver um template específico mais
adequado ao fluxo.

### 12.2. Templates

Manter os sete templates já documentados e acrescentar ao catálogo:

- `retomada_atendimento`;
- `pagamento_confirmado`;
- `comprovante_sem_correspondencia`.

Os corpos e parâmetros serão definidos no repositório. Cadastro, submissão e
aprovação serão realizados externamente na Meta e não serão tratados como
concluídos pelo código.

### 12.3. Ordem da implementação

WA-05 e WA-06 foram incorporadas. Os arquivos compartilhados foram revisados;
os envios iniciais de botões à gestão usam templates e a confirmação ao
inquilino passa pela política central.

### 12.4. O que fazer com uma resposta que não pôde ser entregue

Foram consideradas três opções:

1. **Armazenar a resposta e enviá-la automaticamente depois.** Preserva o texto
   original, mas exige estado pendente, expiração, idempotência, retry e uma
   regra para detectar se a resposta ficou desatualizada.
2. **Recalcular no próximo turno.** Envia `retomada_atendimento`; quando o
   inquilino responder, o agente usa o histórico e produz uma resposta atual.
3. **Enviar a resposta inteira como parâmetro de template.** Entrega o conteúdo
   imediatamente, mas usa um bloco quase arbitrário dentro do template e pode
   ser recusado pela Meta.

Decisão final: **recalcular a resposta no próximo turno**.

Justificativas:

- é um caso excepcional e não justifica uma fila/tabela própria nesta task;
- `conversation_logs` já preserva o contexto normalmente;
- uma resposta recalculada considera o estado mais recente do contrato e das
  cobranças;
- evita entregar automaticamente uma orientação que ficou antiga enquanto a
  janela estava fechada;
- mantém a WA-08 focada na política de envio, sem criar uma nova máquina de
  estados para mensagens pendentes.

Se no futuro as métricas mostrarem que esse fallback ocorre com frequência, o
armazenamento de respostas pendentes poderá ser desenhado como uma task
separada, com idempotência e expiração explícitas.
