# Checkup final das Tasks WA-01 a WA-09

## 1. Objetivo deste documento

Este documento registra os pontos em aberto encontrados na auditoria final
das Tasks WA-01 a WA-09 do plano de integração com a WhatsApp Cloud API.

A auditoria comparou os requisitos de `plano.md` com:

- o código presente na branch `feat/integracao-wa06-wa08`;
- as migrations e RPCs do Supabase;
- o catálogo de templates da Meta;
- os testes unitários existentes;
- a compilação do frontend.

A maior parte das tasks está implementada, mas o conjunto ainda não pode ser
considerado 100% pronto para homologação integrada. Existem lacunas de
integração, segurança, compatibilidade de template, testes e documentação.

Nenhum dos pontos abaixo significa que todas as implementações precisam ser
refeitas. São correções localizadas necessárias para conectar corretamente as
peças que já existem.

## 2. Resumo executivo

| Prioridade | Ponto em aberto | Impacto |
|---|---|---|
| Bloqueador | Download real de mídia não conectado ao webhook | Comprovantes reais enviados pela Meta não chegam ao A2 |
| Alta | Validação insuficiente do host da URL de mídia | Uma URL HTTPS inesperada poderia receber o token usado no download |
| Alta | A3 usa template do A5 com quantidade incorreta de parâmetros | Notificação real de manutenção pode ser rejeitada pela Meta |
| Média | Quatro testes do A4 usam assinatura antiga | A suíte unitária completa não está verde |
| Baixa | README de integração termina na Migration 019 | Ambiente de teste pode ser criado sem a RPC da janela de 24 horas |

## 3. Ponto 1 — download real de comprovantes não está conectado

### O que já existe

A WA-03 implementou em `app/tools/whatsapp_client.py::baixar_midia`:

1. consulta dos metadados da mídia na Graph API;
2. obtenção da URL temporária;
3. download dos bytes;
4. validação de MIME;
5. limite configurável de tamanho;
6. timeout e retry seletivo;
7. retorno tipado com bytes e MIME.

Essa implementação possui testes unitários com transporte HTTP simulado.

### O que acontece atualmente no webhook

Quando uma mensagem real de imagem ou PDF chega, o orquestrador chama a
função local:

`app/orchestrator/processar_mensagem.py::_baixar_midia_whatsapp`.

Essa função ainda é um stub antigo. Mesmo com token configurado, ela termina
em `NotImplementedError`. Portanto, o código funcional da WA-03 existe, mas o
webhook não o utiliza.

O `dev_chat` não revela esse problema porque a mídia simulada já chega em
base64 pelo campo interno `_dados_base64`, sem precisar passar pela Media API.

### Impacto prático

- Imagem simulada no `dev_chat`: funciona.
- Imagem ou PDF real enviado pela Meta: o download falha.
- O A2 não recebe o comprovante real.
- O inquilino recebe o fallback informando que o arquivo não pôde ser
  baixado.

Isso impede o critério de aceitação ponta a ponta de comprovantes reais.

### Correção recomendada

Substituir o stub local por uma integração com
`whatsapp_client.baixar_midia`:

1. receber o `media_id` do webhook;
2. chamar `whatsapp_client.baixar_midia(media_id)`;
3. converter os bytes retornados para base64 somente na fronteira exigida
   pelo A2;
4. usar o `mime_type` devolvido pelo cliente, em vez de confiar apenas no
   MIME presente no payload inicial;
5. encaminhar base64 e MIME para `rotear_comprovante_a2`.

Recomenda-se remover `_baixar_midia_whatsapp` ou transformá-la em um adaptador
pequeno, sem implementar novamente a lógica HTTP.

### Testes necessários

- Payload real com `media_id`, sem `_dados_base64`, chama `baixar_midia`.
- Os bytes são convertidos corretamente para base64.
- O MIME retornado pelo cliente é o MIME entregue ao A2.
- Erro de download produz fallback controlado.
- Arquivo inválido ou grande não chega ao A2.
- O fluxo simulado com `_dados_base64` continua funcionando.

## 4. Ponto 2 — validação insuficiente da URL de download

### Comportamento atual

Depois da consulta de metadados, `baixar_midia` verifica somente se a URL
começa com `https://`.

Isso bloqueia URLs sem TLS, mas aceita qualquer host HTTPS. Em seguida, o
cliente realiza o download enviando o header de autenticação.

### Por que isso é importante

O requisito da WA-03 determina que uma URL inesperada deve ser recusada. A
verificação apenas do protocolo não é suficiente para cumprir esse requisito.

Se uma resposta malformada ou comprometida informasse uma URL como
`https://dominio-inesperado.example/arquivo`, o código atual tentaria acessar
esse host. Isso cria risco de envio do token para um destino indevido.

### Correção recomendada

1. interpretar a URL com um parser de URL;
2. exigir o protocolo HTTPS;
3. validar o hostname contra os hosts oficialmente esperados para download
   de mídia da Meta;
4. recusar username, password, porta ou formato inesperado, caso não sejam
   necessários;
5. nunca incluir a URL assinada completa em logs ou exceções.

A lista de hosts permitidos deve ser confirmada na documentação oficial da
Meta no momento da implementação. Não é recomendável inventar uma lista sem
essa confirmação.

### Testes necessários

- URL oficial HTTPS aceita.
- URL HTTP rejeitada.
- URL HTTPS em host arbitrário rejeitada antes do segundo GET.
- URL malformada rejeitada.
- Nenhuma requisição é feita ao host recusado.
- Token e URL assinada não aparecem em logs ou mensagens de erro.

## 5. Ponto 3 — incompatibilidade entre a notificação do A3 e o template do A5

### O fluxo correto do A5

O template `escalonamento_equipe` está documentado com três variáveis, nesta
ordem:

1. protocolo;
2. motivo;
3. descrição.

O fluxo principal do A5 chama
`notificar_staff_escalonamento(protocolo, motivo, descricao)` e envia os três
parâmetros corretamente.

### O problema no A3

Quando o A3 abre um ticket de manutenção, ele produz uma mensagem pronta em
`resultado.notificacao_gestora` e chama `notificar_staff(mensagem)`.

Essa função reutiliza o mesmo template `escalonamento_equipe`, mas envia apenas
um parâmetro. O catálogo da Meta define três variáveis para esse template.

Os testes atuais apenas verificam se o cliente Python recebeu uma lista com
um item. Eles não simulam a validação do template cadastrado na Meta, por isso
o problema não aparece nos unitários.

### Impacto prático

Com envio real ativo, a Meta pode rejeitar o template por quantidade ou
estrutura incorreta de parâmetros. O ticket de manutenção pode já ter sido
criado no banco, mas a gestão não receberá a notificação esperada.

### Correção recomendada

Criar um template específico para manutenção, por exemplo
`manutencao_equipe`.

Essa é a opção recomendada porque manutenção e escalonamento possuem modelos
de domínio e finalidades diferentes. Reutilizar `escalonamento_equipe`
forçaria o A3 a inventar protocolo ou motivo de escalonamento que não
representam corretamente um ticket de manutenção.

Há duas formas possíveis de estruturar o novo template:

1. uma variável contendo a mensagem pronta atual;
2. variáveis separadas para protocolo, imóvel, categoria, urgência e
   descrição.

A segunda forma é mais estruturada e tende a ser mais fácil de revisar, mas
exige derivar os campos diretamente do modelo de ticket. A decisão deve ser
confirmada antes da implementação e do cadastro na Meta.

### Testes necessários

- A3 usa o novo nome de template.
- Parâmetros seguem exatamente a ordem documentada.
- A5 continua usando `escalonamento_equipe` com três parâmetros.
- Falha no aviso não apaga o ticket já criado.
- Modo simulado não exige telefone ou credenciais.

### Dependência externa

O novo template precisará ser cadastrado e submetido na plataforma da Meta.
A existência do código e da documentação não representa aprovação externa.

## 6. Ponto 4 — quatro testes do A4 estão desatualizados

### Causa

`processar_finalizacao_contrato` passou a funcionar como dispatcher do tipo
de renovação e atualmente exige três funções injetadas:

1. `finalizar_contrato_fn`;
2. `desativar_pendente_renovacao_fn`;
3. `transicionar_indeterminado_fn`.

Quatro testes em `tests/test_a4_fluxo.py` ainda fornecem somente
`finalizar_contrato_fn`, usando o contrato anterior da função. O erro ocorre
antes de a regra de negócio ser executada:

`TypeError: processar_finalizacao_contrato() missing 2 required keyword-only arguments`.

### Interpretação

As falhas não foram causadas pelas alterações da WA-08 nem pelo novo fluxo de
botões. O histórico mostra que a assinatura mudou depois dos testes originais,
durante alterações no fluxo de renovação.

O caminho real de `executar_alertas_contratuais` fornece os três callbacks.
Portanto, o indício principal é de testes desatualizados, não de uma chamada
de produção incompleta.

Mesmo assim, a Definition of Done exige a suíte unitária verde. Enquanto os
quatro testes falharem, esse critério não está cumprido.

### Correção recomendada

Atualizar os quatro testes para:

- fornecer fakes para as três funções;
- definir explicitamente o `tipo_renovacao` do contrato usado no cenário;
- verificar o retorno atual, que pode ser uma tupla com status e ID;
- confirmar que apenas o callback correspondente ao tipo de renovação foi
  chamado;
- manter o guard de `prazo_indeterminado` coberto.

Também é recomendável ter cenários separados para:

- finalização de `novo_contrato`;
- pendência de renovação;
- transição para prazo indeterminado;
- contrato fora da data de término;
- contrato que já está em prazo indeterminado.

Não se recomenda alterar a assinatura atual apenas para fazer os testes
antigos passarem, pois isso poderia enfraquecer o fluxo mais novo de renovação.

## 7. Ponto 5 — documentação do Supabase de teste termina na Migration 019

### Situação atual

`docs/setup-supabase.md` lista corretamente a Migration 020, que cria a RPC
`agent_get_last_tenant_message_at` usada pela política de 24 horas.

Porém, `tests/integration/README.md` ainda instrui aplicar as migrations apenas
até `019_normalizacao_telefone.sql`.

### Impacto prático

Se um novo Supabase de teste for preparado seguindo somente o README de
integração:

- a Migration 020 não será aplicada;
- a RPC da janela de 24 horas não existirá;
- consultas da janela falharão;
- a política segura usará template como fallback;
- um teste real de texto livre dentro da janela não representará o ambiente
  correto.

### Correção recomendada

Atualizar `tests/integration/README.md` para:

- incluir a Migration 020;
- explicar que ela depende de `agent_contract_id()` e de
  `conversation_logs`;
- manter a orientação de aplicar todas as migrations em ordem;
- adicionar uma verificação simples da existência da RPC antes dos testes da
  WA-08.

## 8. Status detalhado das Tasks WA-01 a WA-09

| Task | Estado da implementação | Observação |
|---|---|---|
| WA-01 | Implementada | Configuração, kill switch, exceções, resultados, URL configurável e logs seguros estão presentes |
| WA-02 | Implementada | Texto e template usam HTTP com timeout, retry seletivo e testes de payload/erro |
| WA-03 | Parcial | Botões e cliente de mídia existem, mas faltam integração com webhook e validação segura do host |
| WA-04 | Parcial | Texto, status, clique e `dev_chat` estão coerentes; mídia real continua bloqueada pelo stub |
| WA-05 | Parcial | A2 e fluxo estruturado do A5 estão corretos; o notificador genérico usado pelo A3 não corresponde ao template |
| WA-06 | Implementada | IDs, webhook e botões funcionam; o fluxo final aprovado substitui `Só uma delas` em mensagens novas |
| WA-07 | Implementada | Helper Python, migration, índice, RPC e normalização no frontend estão presentes |
| WA-08 | Implementada no código | Política central, limite exato de 24 horas, fallback seguro e Migration 020 existem |
| WA-09 | Implementada com pendência de testes | Transporte do A4 e catálogo existem; quatro testes do A4 precisam ser atualizados |

## 9. Decisões posteriores ao plano original

Algumas diferenças entre `plano.md` e o código não foram classificadas como
erro porque refletem decisões posteriores aprovadas pelo time.

### Alertas de renovação e reajuste

O plano original possui um trecho que menciona notificação do A4 ao
inquilino. A decisão posterior foi enviar renovacao e reajuste para a gestão
por template. O código e o catálogo atual seguem essa decisão posterior:

- destino `WHATSAPP_STAFF_PHONE_NUMBER`;
- template `alerta_contratual`;
- destinatários Domingos/Fernanda.

Essa diferença é intencional.

### Pagamento combinado

O fluxo provisório de `Só uma delas` foi substituído por:

1. `Cobre os dois`;
2. `Água paga`;
3. `Aluguel pago`.

Isso ocorre somente quando existem exatamente uma cobrança de água e uma de
aluguel. Tipos repetidos e conjuntos ambíguos seguem para resolução manual,
sem botões e sem alteração automática de status.

Callbacks antigos de `Só uma delas` continuam aceitos apenas para mensagens
enviadas antes da mudança.

## 10. Validações executadas durante o checkup

### Backend

Testes diretamente relacionados às WA-01 a WA-09:

- 209 testes passaram;
- 4 testes falharam;
- as quatro falhas são os testes desatualizados de
  `TestProcessarFinalizacaoContrato`.

Na suíte unitária ampla observada durante a validação:

- 316 testes passaram;
- os mesmos 4 testes do A4 falharam.

O comando `git diff --check` passou.

### Frontend

O build de produção passou, incluindo a compilação da normalização de
telefone da WA-07.

Os diretórios gerados pelo build foram removidos depois da verificação e não
fazem parte das alterações do repositório.

### Credenciais

Somente `.env.example` e `.env.test.example` estão rastreados pelo Git. Não
foi encontrada atribuição preenchida das principais variáveis secretas nos
arquivos rastreados.

### Integrações externas

As integrações reais não foram executadas durante o checkup. Elas mutam um
Supabase de teste e algumas chamam a Anthropic. Devem ser executadas somente
em ambiente de teste confirmado e separado de produção.

Também não foi presumido que os templates estejam cadastrados ou aprovados na
Meta.

## 11. Ordem recomendada de correção

1. Conectar `whatsapp_client.baixar_midia` ao processamento real do webhook.
2. Implementar validação segura do host da URL de mídia.
3. Definir e documentar o template específico de manutenção do A3.
4. Atualizar os testes de finalização do A4.
5. Atualizar o README das integrações para incluir a Migration 020.
6. Executar novamente toda a suíte unitária.
7. Aplicar as migrations em um Supabase de teste novo ou validado.
8. Executar os testes de integração.
9. Cadastrar ou atualizar os templates na Meta.
10. Executar a homologação da WA-10 com evidências reais.

## 12. Critérios para considerar WA-01 a WA-09 concluídas em conjunto

As tasks podem ser consideradas integradas e coerentes quando:

- um payload real de imagem/PDF baixar a mídia e chegar ao A2;
- URL de mídia fora dos hosts permitidos for recusada antes do download;
- A3 e A5 usarem templates compatíveis com seus respectivos parâmetros;
- a suíte unitária completa estiver verde;
- a documentação do Supabase incluir a Migration 020;
- as migrations 019 e 020 forem validadas em banco de teste;
- os testes de integração afetados passarem ou tiverem skips justificados;
- os templates necessários estiverem cadastrados e aprovados externamente;
- o kill switch for validado no ambiente de homologação.

Até esses pontos serem concluídos, a branch possui uma base funcional forte,
mas não deve ser declarada pronta para homologação ponta a ponta com mídia
real.
