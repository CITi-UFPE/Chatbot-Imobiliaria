# Agente de Gestão Contratual — mapeamento de fluxo (A4)

Status: **implementado (feat/agente-gestao-contratual-a4)** — job diário completo: alerta de
renovação D-60, cálculo de reajuste D-30 (com busca do índice IGPM/IPCA na API do Banco Central) e
aplicação automática do reajuste confirmado no aniversário do contrato. Não testado ainda contra o
cron real do Railway nem contra um projeto Supabase real (migration 010 não aplicada em produção) —
ver "Limitações e pendências" abaixo.

## Arquitetura

- `app/models/contract_alerts.py` — `ContratoParaAlerta` (espelha `cron_listar_contratos_ativos`),
  `AlertaRenovacao`, `CalculoReajuste`, `ReajusteAplicado`, e os tipos `IndiceReajuste`,
  `TipoAlerta`, `DecisaoGestora`.
- `app/tools/calculo_reajuste.py` — funções puras, sem I/O: `esta_na_janela_alerta_renovacao`,
  `esta_na_janela_calculo_reajuste`, `proximo_aniversario_contrato`,
  `calcular_periodo_contrato_meses`, `calcular_valor_reajustado`, `identificar_clausula_reajuste`.
- `app/tools/indice_reajuste_client.py` — busca o percentual acumulado de 12 meses do IGPM/IPCA na
  API pública do Banco Central (SGS, sem autenticação); compõe as variações mensais (não soma
  simples).
- `app/tools/mensagens_gestao_contratual.py` — builders de texto (alerta de renovação, cálculo de
  reajuste). Só retornam a string — não enviam nada (mesma decisão do A3: sem canal de WhatsApp
  configurado ainda).
- `app/tools/contract_alerts_client.py` — leitura em lote via RPCs `cron_*` com um client
  autenticado como `cron_batch` (`app/orchestrator/agent_auth.py::obter_client_cron_batch`) — o
  mesmo papel batch já usado pelo A2 (`origin/develop`, migration 008), estendido aqui com as 3
  funções de listagem do A4; escrita (`registrar_alerta_renovacao`, `registrar_calculo_reajuste`,
  `aplicar_reajuste`) via RPCs `agent_*` com um client `agente_ia` escopado ao contrato
  (`obter_client_agente(contract_id)`) — `cron_batch` nunca escreve, ver "Decisões e limitações
  conhecidas" abaixo.
- `app/agents/a4_gestao_contratual/fluxo.py` — `executar_alertas_contratuais`: lista contratos
  ativos, roda os dois fluxos por contrato (isolando erro por contrato — uma falha na API do Banco
  Central para 1 contrato não impede os demais de serem verificados no mesmo dia) e aplica os
  reajustes já confirmados cujo aniversário é hoje.
- `docs/schemas/010_alertas_contratuais_e_reajuste.sql` — adiciona `'ipca'` a
  `contracts.indice_reajuste`, índice único de idempotência em `contract_alerts`, estende o papel
  `cron_batch` (`origin/develop`, migration 008) com 3 funções `cron_listar_*` de leitura, e cria 3
  funções `agent_*` de escrita no papel `agente_ia` (todas `SECURITY DEFINER`). Renumerada de 006
  para 010 — `origin/develop` já ocupou 006-009 (ver `docs/specs/a4-ajustes-pre-merge.md`).
- `app/jobs/cron_alertas_contratuais.py` — já existia (branch `feat/jwt-webhook-a5`), só chamava
  `app.agents.a4_gestao_contratual.executar_alertas_contratuais`, que agora existe.
- 6 arquivos de teste, 57 testes, sem custo de API real (Banco Central e Supabase mockados nos
  testes automatizados; ver `scripts/rodar_a4_gestao_contratual.py` para o teste manual com a API
  real do Banco Central).

## Decisões e limitações conhecidas

**Papel `cron_batch` (reaproveitado de `origin/develop`), só leitura — a escrita usa `agente_ia`.**
O agente conversacional (A1-A3, A5) autentica com um JWT escopado a UM `contract_id` —
`agent_contract_id()` restringe toda política de RLS àquele contrato. O job diário do A4 precisa
enxergar TODOS os contratos ativos de uma vez para decidir quais entraram na janela de alerta; não
existe um `contract_id` para escopar essa *leitura* nesse momento. `origin/develop` já resolveu o
mesmo problema para o cron diário de cobrança do A2 (migration 008): um papel dedicado, só leitura,
`cron_batch`, com `GRANT EXECUTE` só nas funções de listagem que cada agente precisa (nunca
`SELECT` direto nas tabelas). Em vez de criar um segundo papel batch do zero (era `job_ia` numa
versão anterior desta branch), o A4 estende o `cron_batch` existente com suas próprias 3 funções
`cron_listar_*` — ver `docs/specs/a4-ajustes-pre-merge.md`, Parte 1, item 3, para o histórico dessa
decisão.

A *escrita*, ao contrário, é sempre uma ação sobre UM contrato específico (registrar um alerta,
aplicar um reajuste) — não há motivo para abrir mão do isolamento por contrato que
`agent_contract_id()` já garante. As 3 funções de escrita (`agent_registrar_alerta_renovacao`,
`agent_registrar_calculo_reajuste`, `agent_aplicar_reajuste`, migration 010 seção 10.4) usam o papel
`agente_ia` de sempre, seguindo o mesmo padrão de `agent_open_maintenance_ticket`/
`agent_create_escalation` (migration 002): nem recebem `contract_id` como parâmetro, leem
`agent_contract_id()` direto do claim do JWT — não existe a possibilidade de o job escrever no
contrato errado, porque o parâmetro simplesmente não existe. `agent_aplicar_reajuste` também
reforça, dentro da própria função SQL, o filtro de `decisao_gestora`/`valor_aplicado is null` que
`cron_listar_reajustes_para_aplicar` já aplica na leitura — defesa em profundidade contra o alerta
mudar de estado entre a leitura da lista do dia e a escrita de cada item; se a condição não bater
mais, a função devolve `null` em vez de aplicar, e `app/tools/contract_alerts_client.py::aplicar_reajuste`
propaga isso como `False` (não um sucesso silencioso) — `fluxo.py::_aplicar_reajustes_confirmados`
registra isso em `resultado.erros`. `contract_alerts_client.py` assina um token por contrato
(`obter_client_agente(contract_id)`) antes de cada escrita; `cron_batch` nunca é usado para isso.
`assinar_token_cron_batch`/`obter_client_cron_batch` já existiam em `origin/develop`
(`app/orchestrator/agent_auth.py`) e foram trazidos para esta branch nos mesmos moldes, para reduzir
o conflito de merge quando as duas branches se juntarem.

**Percentual do IGPM/IPCA vem da API pública do Banco Central (SGS), em tempo real.** Diferente do
WhatsApp Business API (exige credenciais de conta comercial), a série histórica de ambos os índices
é pública e gratuita, sem autenticação — não há necessidade de tabela interna mantida manualmente
pela gestora nem de integração paga. `buscar_percentual_acumulado_12_meses` busca os últimos 13
registros mensais publicados e compõe (não soma) as últimas 12 variações.

**`'ipca'` adicionado a `contracts.indice_reajuste`.** O schema anterior (migrations 001-003) só
aceitava `'igpm'` e `'livre_negociacao'`. O Fluxo B descrito para o A4 suporta os dois índices —
migration 010 amplia o `CHECK constraint`.

**`decisao_gestora` de `contract_alerts` é compartilhado entre os dois tipos de alerta, mas nem
todo valor se aplica aos dois.** `'encerrar'` é uma decisão do Fluxo A (renovação) sem sentido para
um `calculo_reajuste_d30` — a RPC `cron_listar_reajustes_para_aplicar` só considera
`'renovar_sugerido'`/`'renovar_ajustado'` para decidir o que aplicar, ignorando `'encerrar'` nesse
contexto.

**Não existe uma coluna separada para "valor ajustado pela gestora".** `contract_alerts` só tem
`valor_sugerido` (preenchido pelo agente) e `valor_aplicado` (preenchido no aniversário). Quando a
gestora escolhe `'renovar_ajustado'` (edita o valor sugerido em vez de só confirmar), a edição é
feita direto em `valor_sugerido` via `staff_full_access` (RLS já existente desde a migration 002) —
o valor final aplicado em `agent_aplicar_reajuste` é sempre o que estiver em `valor_sugerido` no
momento do aniversário, seja ele o original ou o editado. Isso é uma decisão de schema, não uma
migration nova: adicionar uma segunda coluna só para "valor ajustado" duplicaria a fonte de
verdade sem necessidade.

**Registro da decisão da gestora (Fluxos A e B) é 100% frontend (Lovable), fora deste PR.** A
policy `staff_full_access` em `contract_alerts` (migration 002) já permite que qualquer
`staff_users` escreva `decisao_gestora`/`valor_sugerido` diretamente — não existe, nem precisa
existir, nenhuma função de escrita do agente para isso. O A4 só lê o resultado dessa decisão
(`cron_listar_reajustes_para_aplicar`) quando chega a hora de aplicar.

**"Aplicar automaticamente" só existe no Fluxo B, não no Fluxo A.** O fluxo descrito para renovação
termina em "gestores registram decisão... para que seja carregado de volta no banco de dados" — uma
escrita direta da gestora, sem nenhuma ação automática do sistema no dia do término. Só o Fluxo B
("quando a data limite é atingida, o sistema atualiza o valor automaticamente") tem uma etapa de
aplicação automatizada (`agent_aplicar_reajuste`, rodando dentro do mesmo `executar_alertas_contratuais`
diário, verificando se hoje é o aniversário de algum reajuste já confirmado).

**Menções fixas ("@Domingos Monteiro @Fernanda Monteiro"), não por imóvel.** Não há, hoje, uma
tabela ligando gestores a imóveis/grupos de WhatsApp específicos — os dois são os únicos gestores do
portfólio (`staff_users`, migration 002). Nota: o texto original do fluxo fornecido tinha "Fernada"
sem o "n" — corrigido para "Fernanda" (grafia usada em todo o resto do projeto).

**Notificação ao grupo de WhatsApp é só texto, sem canal de envio.** Mesma limitação documentada em
`docs/specs/agente-manutencao.md` — o WhatsApp Business API ainda não está configurado no projeto.
`executar_alertas_contratuais` retorna as mensagens já persistidas/montadas; quem for integrar
precisa só plugar o envio de fato.

**Isolamento de erro por contrato, não por lote inteiro.** Diferente do A3 (uma conversa = um
contrato, erro pode propagar), o A4 processa N contratos numa única execução diária — um erro num
contrato (ex: API do Banco Central fora do ar bem na hora do cálculo de reajuste de 1 contrato) é
capturado e registrado em `ResultadoExecucaoAlertas.erros`, sem impedir os demais contratos de
serem verificados no mesmo dia.

## Visão geral

**Escopo do agente:** verificar diariamente todos os contratos ativos, identificar quais entraram
nas janelas de alerta (D-60) ou de cálculo de reajuste (D-30), montar as mensagens correspondentes,
persistir o alerta, e aplicar o reajuste confirmado no aniversário. Tudo que envolve decisão humana
(renovar, renegociar, encerrar, confirmar/ajustar valor) é responsabilidade da gestora via
interface de gestão — o agente nunca decide sozinho.

```
Job diário (1x/dia)
   ↓
[Fluxo A] Para cada contrato ativo:
   data_termino - hoje == 60 dias?
      → registra alerta_renovacao_d60 (idempotente por dia)
      → monta mensagem e retorna para envio ao grupo WhatsApp do imóvel
   ↓
[Fluxo B] Para cada contrato ativo com índice igpm/ipca:
   próximo aniversário anual - hoje == 30 dias?
      → busca percentual acumulado 12 meses (API Banco Central)
      → calcula valor sugerido
      → registra calculo_reajuste_d30 (idempotente por dia)
      → monta mensagem e retorna para envio ao grupo WhatsApp do imóvel
   ↓
[Fluxo B — aplicação] Para cada alerta de reajuste já confirmado/ajustado:
   aniversário do contrato é hoje?
      → aplica valor_sugerido em contracts.valor_aluguel
      → marca alerta como aplicado
FIM — agente encerra participação até o próximo dia
```

## Fluxo A — Alerta de renovação (D-60)

**Gatilho:** `data_termino - hoje == 60 dias`.

**Mensagem (grupo WhatsApp oficial do imóvel):**

> "@Domingos Monteiro @Fernanda Monteiro, o contrato do {identificacao_imovel} ({nome_inquilino})
> completa {periodo_contrato} no dia {data_aniversario_contrato}, daqui a 60 dias.
>
> Será necessário tomar a decisão quanto à renovação, renegociação ou encerramento do contrato."

`periodo_contrato` é a duração total do contrato (`data_termino - data_inicio`, em meses — ex: "12
meses", "30 meses"). `data_aniversario_contrato`, neste fluxo, é `data_termino` (fim da vigência
atual).

Depois disso, a decisão (renovar / renegociar / encerrar) e o registro de volta no banco são 100%
responsabilidade da gestora via interface de gestão — o A4 não monitora nem cobra essa decisão.

## Fluxo B — Cálculo de reajuste (D-30)

**Gatilho:** `próximo_aniversário_anual(data_inicio) - hoje == 30 dias`. Diferente do Fluxo A, esse
aniversário é anual e recorrente (12, 24, 36... meses desde a assinatura), independente de quando o
contrato termina — um contrato de 30 meses tem 2 aniversários de reajuste antes de chegar ao fim da
vigência.

Não se aplica a contratos com `indice_reajuste = 'livre_negociacao'` ou sem índice definido — não
há cálculo automático possível sem um índice publicado.

**Cálculo:** busca o percentual acumulado de 12 meses do índice (IGPM ou IPCA) na API do Banco
Central e aplica sobre o valor atual do aluguel.

**Mensagem (grupo WhatsApp oficial do imóvel):**

> "@Domingos Monteiro @Fernanda Monteiro, segue o cálculo de reajuste do contrato do
> {identificacao_imovel} ({nome_inquilino}), com data de aniversário em
> {data_aniversario_contrato}.
>
> Índice aplicável (conforme cláusula {numero_clausula_reajuste}): {indice_reajuste}
> Valor atual do aluguel: R$ {valor_atual}
> Percentual de reajuste: {percentual_reajuste}%
> Novo valor sugerido: R$ {valor_reajustado}"

`numero_clausula_reajuste` é identificado buscando, entre as cláusulas de categoria `financeiro` do
contrato, a primeira que menciona reajuste/índice/correção monetária (busca por radical de palavra,
não LLM — ver `identificar_clausula_reajuste`). Se nenhuma cláusula for encontrada, a mensagem diz
"cláusula não identificada" em vez de quebrar.

**Aplicação automática:** quando a gestora confirma ou ajusta o valor sugerido na plataforma
(`decisao_gestora` = `'renovar_sugerido'`/`'renovar_ajustado'`), o próprio job diário, ao identificar
que o aniversário do contrato chegou, atualiza `contracts.valor_aluguel` automaticamente — sem
esperar nenhuma ação adicional do agente.
