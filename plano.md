# Sprint — Integração com WhatsApp Cloud API


## Objetivo da sprint


Em 7 dias úteis, deixar o backend pronto para homologação ponta a ponta com o número de teste da Meta:


> Uma mensagem enviada por um celular autorizado entra pelo webhook, é processada pelo agente correto e a resposta volta ao WhatsApp. Comprovantes reais podem ser baixados, e notificações do A2, A4 e A5 podem ser enviadas com texto, template ou botões sem quebrar os crons existentes.


Esta sprint não inclui ativação com inquilinos reais, go-live dos 12 imóveis, métricas de entrega nem deduplicação distribuída com Redis.


## Como usar este documento com IAs CLI


Cada task abaixo foi escrita para ser entregue isoladamente a uma IA CLI. Ao iniciar uma task:


1. informe à IA o ID da task e cole a seção completa;
2. peça que ela leia primeiro os arquivos indicados e quaisquer `AGENTS.md` aplicáveis;
3. mantenha uma branch por task
4. não permita mudanças fora do escopo sem justificativa explícita;
5. exija testes e um resumo final com arquivos alterados, decisões, comandos executados e riscos restantes.


As tasks marcadas como dependentes só devem começar depois que a dependência estiver integrada ou disponível na branch da IA.


## Regras comuns para todas as tasks


- Preserve as assinaturas públicas existentes sempre que possível.
- Não use credenciais reais em testes, fixtures, logs ou commits.
- Toda chamada HTTP deve ter timeout explícito.
- Nunca registre `WHATSAPP_ACCESS_TOKEN` ou conteúdo binário completo em logs.
- Testes unitários não podem acessar Meta, Supabase ou Anthropic de verdade.
- Preserve o funcionamento do `dev_chat` sem disparar mensagens externas.
- Não altere texto de cobrança validado pelo cliente sem necessidade técnica.
- Antes de editar, verifique `git status` e preserve mudanças preexistentes.
- Use `pytest` para validar o backend e reporte testes não executados com o motivo.
- Commits, pushes, merges e alterações em serviços externos não fazem parte da task, salvo autorização expressa.


## Mapa de dependências


| Task | Responsável | Depende de | Pode rodar em paralelo com |
|---|---|---|---|
| WA-01 | Pessoa 1 | — | WA-04, WA-07, WA-09 |
| WA-02 | Pessoa 1 | WA-01 | WA-05, WA-07 |
| WA-03 | Pessoa 1 | WA-01 | WA-05, WA-07 |
| WA-04 | Pessoa 2 | — | WA-01, WA-07, WA-09 |
| WA-05 | Pessoa 2 | WA-01, WA-04 | WA-02, WA-07 |
| WA-06 | Pessoa 2 | WA-01, WA-03 | WA-08 |
| WA-07 | Pessoa 3 | — | WA-01, WA-04 |
| WA-08 | Pessoa 3 | WA-01 | WA-06 |
| WA-09 | Pessoa 3 | — | WA-01, WA-04, WA-07 |
| WA-10 | Trio | WA-02 a WA-09 | — |


## Distribuição sugerida


### Pessoa 1 — Transporte Meta


- WA-01 — Fundação do cliente WhatsApp
- WA-02 — Envio de texto e template
- WA-03 — Botões e download de mídia


### Pessoa 2 — Integração com os agentes


- WA-04 — Resposta do webhook ao inquilino
- WA-05 — Notificações A2 e A5
- WA-06 — Botões do comprovante


### Pessoa 3 — Regras e homologação


- WA-07 — Normalização de telefone
- WA-08 — Janela de 24 horas e templates proativos
- WA-09 — Transporte do A4 e documentação de templates


### Trio


- WA-10 — Homologação integrada no número de teste


---


## WA-01 — Fundação do cliente WhatsApp


**Responsável:** Pessoa 1  
**Estimativa:** 1 dia  
**Dependências:** nenhuma


### Prompt para a IA CLI


Implemente a fundação de um cliente centralizado da WhatsApp Cloud API em `app/tools/whatsapp_client.py`. Nesta task, crie configuração, modelos/tipos mínimos, validações, exceções e o kill switch, mas não implemente ainda os quatro fluxos HTTP completos de texto, template, botões e mídia.


Leia antes de editar:


- `.env.example`
- `requirements.txt`
- `app/agents/a2_cobranca/notificacao.py`
- `app/agents/a5_escalonamento/notificacao.py`
- `app/orchestrator/processar_mensagem.py`


Implemente:


- leitura centralizada de `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_ENVIO_ATIVO` e `WHATSAPP_GRAPH_API_VERSION`;
- parsing booleano seguro de `WHATSAPP_ENVIO_ATIVO`, com padrão `false`;
- URL base montada a partir da versão configurável da Graph API;
- exceções próprias para configuração, erro transitório, erro permanente e conteúdo inválido;
- um resultado de envio que possa carregar pelo menos `message_id` e indicação de envio real ou simulado;
- helpers internos para headers, timeout e logging seguro;
- stubs públicos e documentados para `enviar_texto`, `enviar_template`, `enviar_botoes` e `baixar_midia`;
- modo simulado: com envio inativo, funções de envio não fazem HTTP e retornam resultado indicando simulação.


Atualize `.env.example` com as duas novas variáveis e comentários claros. Não adicione token real.


### Restrições


- Não altere consumidores em A2, A5, webhook ou orquestrador.
- Não crie um cliente HTTP global mutável.
- Não faça retry nesta task; apenas prepare a estrutura.
- Não escolha silenciosamente uma versão fixa da Graph API sem permitir configuração.


### Critérios de aceite


- Importar o módulo sem variáveis configuradas não gera erro.
- Com `WHATSAPP_ENVIO_ATIVO=false`, nenhum método de envio tenta acessar a rede.
- Com envio ativo e credenciais ausentes, o erro informa quais configurações faltam sem revelar segredos.
- Logs nunca contêm o access token.
- `.env.example` documenta kill switch e versão.


### Testes esperados


Crie `tests/test_whatsapp_client_config.py` cobrindo:


- padrão inativo;
- valores booleanos válidos e inválidos;
- simulação sem chamada HTTP;
- envio ativo sem credenciais;
- montagem da URL base.


Execute:


```powershell
pytest tests/test_whatsapp_client_config.py -q
```


---


## WA-02 — Envio de texto e template


**Responsável:** Pessoa 1  
**Estimativa:** 2 dias  
**Dependências:** WA-01


### Prompt para a IA CLI


Complete `app/tools/whatsapp_client.py` implementando os envios de texto e template pela WhatsApp Cloud API. Use `httpx`, timeout explícito e retry seletivo com `tenacity`.


Leia antes de editar:


- `app/tools/whatsapp_client.py`
- `app/agents/a2_cobranca/mensagens.py`
- `requirements.txt`


Implemente:


- `enviar_texto(telefone, texto)` com `POST /{PHONE_NUMBER_ID}/messages`;
- `enviar_template(telefone, nome, parametros, lang="pt_BR")`;
- normalização mínima do destino para somente dígitos no limite do transporte, sem resolver contratos;
- extração e retorno do `message_id` da resposta da Meta;
- timeout explícito;
- retry apenas para falhas de conexão, timeout, HTTP 429 e HTTP 5xx;
- nenhuma repetição automática para HTTP 4xx permanentes;
- conversão de erros da Meta nas exceções definidas em WA-01;
- logs estruturados com operação, telefone mascarado, status e `message_id`.


Preserve o modo simulado criado em WA-01.


### Restrições


- Não altere ainda A2, A4, A5, webhook ou orquestrador.
- Não use `requests`; o projeto já usa `httpx`.
- Não faça retry indiscriminado de toda exceção.
- Não inclua conteúdo integral de mensagens sensíveis em logs de sucesso.


### Critérios de aceite


- Payload de texto segue o formato esperado pela Cloud API.
- Payload de template suporta parâmetros ordenados no componente `body`.
- A função retorna o ID fornecido pela Meta.
- Erro 400 ocorre uma vez e vira erro permanente.
- Erro 429 ou 5xx é repetido conforme política limitada.
- Kill switch continua impedindo chamadas externas.


### Testes esperados


Crie `tests/test_whatsapp_client_send.py` com `httpx.MockTransport` ou mock equivalente. Cubra sucesso, payloads, 400, 429, 500, timeout, resposta sem `message_id` e simulação.


Execute:


```powershell
pytest tests/test_whatsapp_client_config.py tests/test_whatsapp_client_send.py -q
```


---


## WA-03 — Botões e download de mídia


**Responsável:** Pessoa 1  
**Estimativa:** 2 dias  
**Dependências:** WA-01


### Prompt para a IA CLI


Implemente no cliente WhatsApp o envio de mensagens interativas com botões e o download de mídia real da Meta.


Leia antes de editar:


- `app/tools/whatsapp_client.py`
- `app/agents/a2_cobranca/button_ids.py`
- `app/orchestrator/processar_mensagem.py`


Implemente:


- `enviar_botoes(telefone, corpo, botoes)` com payload `interactive` do tipo `button`;
- validação de 1 a 3 botões;
- validação de título não vazio com até 20 caracteres;
- validação de ID não vazio com até 256 caracteres;
- `baixar_midia(media_id)` em duas etapas: obter metadados/URL assinada e baixar os bytes;
- validação de MIME permitido para comprovantes: imagens comuns e PDF;
- limite de tamanho configurável e conservador;
- retorno contendo bytes e MIME real, ou estrutura equivalente claramente tipada;
- timeout e política de retry coerentes com WA-02;
- recusa de URL inesperada ou resposta malformada sem expor o token.


### Restrições


- Não monte IDs de negócio dentro do cliente; ele recebe IDs prontos.
- Não faça base64 no cliente se a fronteira atual puder trabalhar melhor com bytes. Se mudar o tipo esperado pelo consumidor, documente a decisão para WA-04.
- Não aceite quantidade ilimitada de mídia na memória.


### Critérios de aceite


- Payload interativo contém todos os botões no formato esperado.
- Entradas acima dos limites falham antes de qualquer chamada HTTP.
- Download executa exatamente as duas etapas esperadas.
- MIME ou tamanho inválido produz erro de conteúdo inválido.
- Token é enviado no header necessário, mas nunca aparece em logs ou exceções.


### Testes esperados


Crie `tests/test_whatsapp_client_media_buttons.py` cobrindo limites, payload, download em duas etapas, MIME inválido, arquivo grande, erro HTTP e resposta malformada.


Execute:


```powershell
pytest tests/test_whatsapp_client_media_buttons.py tests/test_whatsapp_client_send.py -q
```


---


## WA-04 — Resposta do webhook ao inquilino


**Responsável:** Pessoa 2  
**Estimativa:** 2 dias  
**Dependências:** nenhuma para preparar testes; WA-01 para integrar o cliente


### Prompt para a IA CLI


Faça com que respostas produzidas pelo processamento de mensagens recebidas sejam enviadas ao WhatsApp quando a origem for o webhook real, sem alterar o comportamento do chat simulado.


Leia antes de editar:


- `app/api/routers/whatsapp.py`
- `app/api/routers/dev_chat.py`
- `app/orchestrator/processar_mensagem.py`
- `app/orchestrator/orchestrator.py`
- `app/tools/whatsapp_client.py`, quando WA-01 estiver disponível


Implemente:


- parâmetro keyword-only `responder_via_whatsapp: bool = False` em `processar_mensagem_recebida`;
- propagação segura do telefone remetente nos caminhos de texto e mídia;
- envio da resposta não vazia pelo cliente WhatsApp quando o parâmetro for `True`;
- webhook chamando o processamento com `responder_via_whatsapp=True`;
- `dev_chat` mantendo o padrão `False` e retornando o texto para a interface;
- tratamento de falha no envio depois do processamento, com log rastreável e sem desfazer efeitos de negócio já concluídos;
- manutenção da resposta HTTP rápida do webhook via `BackgroundTasks`.


Defina explicitamente a política para erros antes de existir contrato: a mensagem segura retornada pelo processamento também deve poder ser enviada ao remetente, sem revelar detalhes internos.


### Restrições


- Não mova o processamento do agente para dentro da requisição síncrona do webhook.
- Não envie resposta a eventos de status sem `messages`.
- Não envie respostas de cliques administrativos ao telefone errado. Cliques da Fernanda devem seguir a regra existente e não receber automaticamente a resposta destinada ao inquilino.
- Não altere a classificação ou lógica interna dos agentes.


### Critérios de aceite


- Mensagem de texto real gera uma chamada de envio para o mesmo `from`.
- Mensagem simulada não chama o cliente WhatsApp.
- Evento de status não envia nada.
- Clique interativo não envia resposta automática ao remetente por engano.
- Falha de transporte não apaga logs ou efeitos do agente.
- O endpoint continua devolvendo `{"status": "recebido"}` antes do processamento pesado.


### Testes esperados


Crie `tests/test_whatsapp_webhook_processing.py` cobrindo texto, mídia, status, clique, contrato não encontrado, falha do cliente e regressão do `dev_chat`.


Execute:


```powershell
pytest tests/test_whatsapp_webhook_processing.py -q
```


---


## WA-05 — Migrar notificações do A2 e A5


**Responsável:** Pessoa 2  
**Estimativa:** 2 dias  
**Dependências:** WA-01, WA-02 e WA-04


### Prompt para a IA CLI


Substitua os caminhos de notificação que hoje apenas logam ou levantam `NotImplementedError` por chamadas ao cliente WhatsApp, preservando as assinaturas públicas e o comportamento seguro com o kill switch desligado.


Leia antes de editar:


- `app/agents/a2_cobranca/notificacao.py`
- `app/agents/a2_cobranca/cobranca.py`
- `app/agents/a2_cobranca/comprovante.py`
- `app/agents/a5_escalonamento/notificacao.py`
- `app/agents/a5_escalonamento/escalonamento.py`
- `app/tools/whatsapp_client.py`
- `tests/test_a2_comprovante_cron.py`


Migre:


- `enviar_mensagem_cobranca`;
- `notificar_fernanda_comprovante`;
- `notificar_fernanda_pagamento_combinado`;
- `notificar_fernanda_sem_match`;
- `responder_confirmacao_pagamento`;
- `notificar_staff` do A5.


Nesta task, use texto livre para caminhos reativos e a abstração de template quando a chamada já fornecer uma mensagem proativa estruturada. A decisão completa de janela de 24 horas será integrada em WA-08.


### Restrições


- Não deixe nenhum `NotImplementedError` condicionado apenas à presença do token.
- Preserve assinaturas para não quebrar consumidores existentes.
- Não engula falhas silenciosamente: produza log com operação e destino mascarado.
- Não altere estados de charge para compensar falha de transporte.
- Não reescreva os textos validados em `mensagens.py`.


### Critérios de aceite


- Preencher token não quebra mais o cron por `NotImplementedError`.
- Kill switch desligado mantém todas as notificações em modo simulado.
- Cada função usa o telefone e conteúdo corretos.
- Falhas do cliente seguem política documentada e não corrompem estado.
- Testes antigos do A2 e A5 continuam passando.


### Testes esperados


Crie `tests/test_notificacoes_whatsapp.py` cobrindo todas as funções públicas, modo simulado, sucesso e falha do cliente.


Execute:


```powershell
pytest tests/test_notificacoes_whatsapp.py tests/test_a2_comprovante_cron.py tests/integration/test_a5_escalonamento_integration.py -q
```


Se o ambiente de integração não estiver configurado, reporte o skip e rode ao menos todos os testes unitários afetados.


---


## WA-06 — Botões do fluxo de comprovante


**Responsável:** Pessoa 2  
**Estimativa:** 1,5 dia  
**Dependências:** WA-01, WA-03 e WA-05


### Prompt para a IA CLI


Conecte as notificações de comprovante do A2 ao envio de botões interativos da Meta, usando exclusivamente as funções de montagem de IDs já existentes.


Leia antes de editar:


- `app/agents/a2_cobranca/button_ids.py`
- `app/agents/a2_cobranca/notificacao.py`
- `app/agents/a2_cobranca/comprovante.py`
- `app/agents/a2_cobranca/orquestrador_a2.py`
- `app/orchestrator/processar_mensagem.py`
- `app/tools/whatsapp_client.py`


Implemente:


- “Confirmar” com `montar_button_id_confirmar`;
- “Valor diverge” com `montar_button_id_divergente`;
- “Cobre os dois” com `montar_button_id_combinado_todos`;
- payloads com títulos dentro do limite da Meta;
- teste de ida e volta: ID montado no envio é aceito por `decodificar_button_id` no recebimento;
- fallback manual para o caso combinado parcial.


O botão “Só uma delas” não pode concluir automaticamente a ação, pois um único clique não identifica qual charge foi paga. Nesta sprint, escolha e documente uma destas soluções conservadoras: omitir o botão e orientar atendimento manual, ou fazer o clique criar/escalar uma pendência sem alterar charges.


### Restrições


- Não invente um ID novo incompatível com `decodificar_button_id`.
- Não confirme, reverta ou altere charges no fallback parcial.
- Não ultrapasse três botões.
- Não altere o significado das ações já suportadas.


### Critérios de aceite


- Os botões enviados são decodificáveis pelo webhook.
- “Confirmar”, “Valor diverge” e “Cobre os dois” chegam às rotas corretas.
- Caso parcial não altera nenhuma cobrança automaticamente.
- IDs e títulos respeitam os limites definidos.


### Testes esperados


Crie `tests/test_a2_whatsapp_buttons.py` com round-trip dos IDs, payloads de notificação e fallback parcial.


Execute:


```powershell
pytest tests/test_a2_whatsapp_buttons.py tests/test_a2_comprovante_cron.py -q
```


---


## WA-07 — Normalização brasileira de telefone


**Responsável:** Pessoa 3  
**Estimativa:** 2 dias  
**Dependências:** nenhuma


### Prompt para a IA CLI


Torne a resolução de contrato robusta às representações brasileiras de telefone recebidas da Meta e gravadas no banco, incluindo variantes com e sem código do país e com e sem nono dígito móvel.


Leia antes de editar:


- `app/orchestrator/processar_mensagem.py`
- `docs/schemas/004_protocolo_e_resolucao_contrato.sql`
- `docs/schemas/README.md`
- `frontend/src/components/gestao/ContratosSection.tsx`
- `frontend/src/lib/database.types.ts`
- fixtures de telefone em `tests/integration/fixtures/contratos.py`


Implemente:


- helper Python puro para remover caracteres de apresentação e gerar candidatos controlados;
- suporte a `55 + DDD + número`, `DDD + número` e forma com `+`;
- variante móvel com e sem nono dígito após o DDD;
- rejeição de entradas vazias, curtas ou ambíguas;
- nova migration incremental, sem editar migrations já aplicadas, para resolver por telefone normalizado;
- índice ou estratégia SQL adequada para evitar varredura desnecessária;
- normalização no cadastro do frontend, se isso puder ser feito sem mudar contratos públicos da API;
- atualização da documentação de schemas e tipos gerados apenas se necessário.


### Restrições


- Não remova todo dígito `9` indiscriminadamente.
- Não edite a migration `004` como se ainda não tivesse sido aplicada; crie a próxima migration numerada disponível.
- Não use `service_role` para resolver o contrato.
- Preserve retorno `uuid` ou `null` da RPC.
- Se dois contratos ativos puderem corresponder ao mesmo telefone normalizado, não escolha silenciosamente: trate como inconsistência.


### Critérios de aceite


- Formatos `+55 (DDD) 9xxxx-xxxx`, `55DDD9xxxxxxxx`, `DDD9xxxxxxxx` e variante Meta sem nono dígito encontram o contrato esperado.
- Telefone fixo não recebe transformação móvel incorreta.
- Entrada inválida não causa exceção não tratada no webhook.
- Colisão entre contratos ativos é detectável.
- Migration é idempotente onde aplicável e documentada.


### Testes esperados


Crie testes unitários para geração de candidatos e testes de integração para a RPC. Use somente o Supabase de teste.


Execute:


```powershell
pytest tests/test_phone_normalization.py -q
pytest -m integration -k telefone -q
```


---


## WA-08 — Janela de 24 horas e templates proativos


**Responsável:** Pessoa 3  
**Estimativa:** 2 dias  
**Dependências:** WA-01 e WA-02


### Prompt para a IA CLI


Implemente uma decisão centralizada entre texto livre e template para mensagens enviadas pelo sistema, respeitando a janela de atendimento de 24 horas desde a última mensagem recebida do inquilino.


Leia antes de editar:


- `app/agents/a2_cobranca/mensagens.py`
- `app/agents/a2_cobranca/notificacao.py`
- `app/agents/a5_escalonamento/notificacao.py`
- `app/orchestrator/processar_mensagem.py`
- migrations e RPCs relacionadas a `agent_log_message`
- `app/tools/whatsapp_client.py`


Implemente:


- modelo explícito de saída, por exemplo texto livre ou template com nome, idioma e parâmetros;
- função que consulte a última mensagem do inquilino para um contrato;
- cálculo timezone-aware da janela de 24 horas;
- política: resposta reativa dentro da janela usa texto; mensagem proativa ou janela fechada usa template;
- mapeamento dos estágios A2 para `aviso_vencimento`, `aviso_atraso` e `aviso_atraso_severo`;
- parâmetros determinísticos e na mesma ordem cadastrada na Meta;
- fallback seguro quando não for possível determinar a janela: usar template, nunca texto livre proativo;
- testes no limite exato da janela.


Se faltar uma RPC adequada para consultar a última mensagem, crie uma migration incremental mínima, preservando RLS e escopo por contrato.


### Restrições


- Não misture a regra de negócio da janela dentro de cada agente.
- Não use horário local sem timezone.
- Não transforme respostas reativas em template sem necessidade.
- Não altere o texto validado do A2; derive os parâmetros necessários de seus modelos de domínio.
- Não trate aprovação externa do template como concluída pelo código.


### Critérios de aceite


- Última mensagem há menos de 24 horas permite texto livre reativo.
- Última mensagem há 24 horas ou mais exige template.
- Ausência ou falha de consulta exige template.
- Cobranças do cron sempre produzem template apropriado.
- Ordem e formatação dos parâmetros são testadas.


### Testes esperados


Crie `tests/test_whatsapp_message_policy.py` cobrindo 23h59, 24h, mais de 24h, ausência de histórico, falha de banco e mapeamento de todos os estágios do A2.


Execute:


```powershell
pytest tests/test_whatsapp_message_policy.py tests/test_a2_comprovante_cron.py -q
```


---


## WA-09 — Transporte do A4 e catálogo de templates


**Responsável:** Pessoa 3  
**Estimativa:** 1,5 dia  
**Dependências:** WA-02 para integração final; documentação pode começar antes


### Prompt para a IA CLI


Conecte as mensagens geradas pelo A4 ao transporte WhatsApp sem perder a capacidade atual de retornar resultados para testes e relatórios. Produza também o catálogo operacional dos templates que precisam ser submetidos à Meta.


Leia antes de editar:


- `app/agents/a4_gestao_contratual/fluxo.py`
- `app/jobs/cron_alertas_contratuais.py`
- `app/tools/mensagens_gestao_contratual.py`
- `tests/test_a4_fluxo.py`
- `tests/test_mensagens_gestao_contratual.py`
- `app/tools/whatsapp_client.py`


Implemente:


- caminho explícito de notificação do A4 para telefone do inquilino;
- envio por template `alerta_contratual` para reajuste e renovação;
- separação entre gerar/registrar o alerta e transportá-lo;
- política de falha que não marque silenciosamente uma mensagem como entregue;
- preservação do resultado estruturado usado pelos testes atuais;
- documento `docs/whatsapp/templates-meta.md` com nome, categoria Utility, idioma, corpo sugerido, ordem das variáveis, exemplo e consumidor de cada template.


Inclua no catálogo:


- `aviso_vencimento`;
- `aviso_atraso`;
- `aviso_atraso_severo`;
- `comprovante_para_conferencia`;
- `pagamento_combinado`;
- `alerta_contratual`;
- `escalonamento_equipe`.


### Restrições


- Não misture chamadas HTTP dentro das funções puras que formatam mensagens.
- Não afirme no documento que um template está aprovado sem evidência externa.
- Não remova retornos atualmente usados por cron ou testes.
- Mantenha tom estritamente transacional nos templates.


### Critérios de aceite


- A4 possui destino e chamada de transporte explícitos.
- Renovação e reajuste usam parâmetros determinísticos.
- Falha de envio é observável e não apaga o alerta de negócio.
- Testes atuais do A4 continuam passando.
- Catálogo permite copiar cada template para o painel da Meta sem adivinhar a ordem das variáveis.


### Testes esperados


Adicione testes ao conjunto do A4 ou crie `tests/test_a4_whatsapp_notification.py` cobrindo renovação, reajuste, simulação e falha de transporte.


Execute:


```powershell
pytest tests/test_a4_whatsapp_notification.py tests/test_a4_fluxo.py tests/test_mensagens_gestao_contratual.py -q
```


---


## WA-10 — Homologação integrada no número de teste


**Responsável:** trio  
**Estimativa:** 2 dias compartilhados  
**Dependências:** WA-02 a WA-09 integradas


### Prompt para a IA CLI


Prepare e valide a homologação integrada da WhatsApp Cloud API no ambiente de staging. A IA deve automatizar apenas o que puder ser feito localmente ou no ambiente de teste autorizado; configurações no painel da Meta, Railway e Supabase devem ser apresentadas como passos para execução humana quando não houver ferramenta ou autorização disponível.


Leia antes de agir:


- `.env.example`
- `.env.test.example`
- `app/api/main.py`
- `app/api/routers/whatsapp.py`
- `app/api/routers/dev_chat.py`
- `tests/integration/README.md`
- `docs/whatsapp/templates-meta.md`
- todos os testes criados nas tasks WA-01 a WA-09


Produza:


- `docs/whatsapp/homologacao-staging.md`;
- lista exata de variáveis necessárias, sem valores secretos;
- procedimento para verificar o webhook GET e um POST assinado;
- matriz de testes ponta a ponta;
- comandos locais seguros para rodar unitários e integrações;
- checklist de inspeção do Supabase após cada cenário;
- seção de evidências com data, executor, número mascarado, cenário, resultado, `message_id` e observação;
- procedimento do kill switch;
- procedimento de rollback de configuração, sem apagar dados.


Execute localmente toda a suíte unitária. Execute integrações reais apenas se o ambiente de teste estiver configurado e claramente separado de produção.


### Matriz mínima


1. A1 responde pergunta contratual.
2. A3 abre manutenção e retorna protocolo.
3. A2 baixa imagem real e processa comprovante.
4. Fernanda confirma pelo botão e a charge muda para `confirmado`.
5. Valor divergente segue o fluxo previsto.
6. Cron envia D−5, D0, D+5, D+10 e D+15 por template.
7. A4 envia alerta contratual.
8. A5 escala e notifica equipe.
9. Telefone desconhecido recebe resposta segura.
10. Mídia inválida ou grande demais falha de modo controlado.
11. Janela aberta usa texto reativo; janela fechada usa template.
12. Kill switch impede envios sem derrubar processamento e crons.


### Restrições


- Nunca usar Supabase, telefone ou contrato de produção.
- Nunca imprimir tokens nos comandos ou documento.
- Não declarar cenário aprovado sem evidência observável.
- Não alterar painel da Meta ou Railway sem autorização explícita.
- Não limpar dados de forma destrutiva fora das fixtures identificadas.


### Critérios de aceite


- Suíte unitária completa verde.
- Integrações afetadas verdes ou skips justificados por falta de credenciais de teste.
- Cada cenário da matriz tem resultado e evidência.
- Os cinco agentes possuem ao menos um fluxo validado pelo transporte real.
- Kill switch foi testado.
- Nenhum segredo entrou no Git.


### Comandos de verificação


```powershell
pytest tests -m "not integration" -q
pytest -m integration -q
git diff --check
git status --short
```


---


## Definition of Done da sprint


A sprint só pode ser encerrada quando:


- [ ] uma mensagem real recebida pelo webhook gera resposta ao mesmo inquilino;
- [ ] o `dev_chat` continua funcional e não envia mensagens externas;
- [ ] imagem e PDF reais podem ser baixados pela Media API;
- [ ] token configurado não provoca `NotImplementedError` nos crons;
- [ ] `WHATSAPP_ENVIO_ATIVO=false` bloqueia todos os envios externos;
- [ ] botões enviados são reconhecidos no retorno pelo webhook;
- [ ] telefone brasileiro é resolvido nas variantes previstas;
- [ ] mensagens fora da janela de 24 horas usam template;
- [ ] A2, A4 e A5 possuem transporte explícito;
- [ ] falhas da Meta são rastreáveis sem exposição de segredo;
- [ ] testes unitários estão verdes;
- [ ] homologação de staging está documentada com evidências;
- [ ] nenhuma credencial ou dado de produção foi usado.


## Fora do escopo desta sprint


- Redis para deduplicação entre instâncias;
- processamento de eventos de entregue e lido;
- dashboard de métricas de mensagens;
- piloto com imóveis reais;
- go-live dos 12 imóveis;
- fluxo automático completo de “Só uma delas”;
- rotação operacional do token permanente;
- alertas automáticos de falha de entrega;
- migração de dados de produção.


## Trilha administrativa paralela


Estas atividades não são tasks de código, mas bloqueiam homologação ou produção:


- [ ] definir o Business Manager proprietário da WABA;
- [ ] escolher número ou chip dedicado;
- [ ] iniciar verificação da empresa;
- [ ] submeter nome de exibição;
- [ ] cadastrar forma de pagamento;
- [ ] cadastrar celulares autorizados no número de teste;
- [ ] submeter os templates Utility até o terceiro dia da sprint;
- [ ] obter credenciais de teste e guardá-las no gerenciador de secrets;
- [ ] confirmar que staging usa Supabase separado de produção.





