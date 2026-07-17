"""Critérios objetivos de escalonamento do A5 — Escalonamento Humano.

Fonte: lista fechada com o Davi/equipe (14/07/2026), a partir da spec
original e da leitura direta dos 8 contratos reais. Cada `motivo` abaixo
corresponde a um valor do CHECK constraint de `escalations.motivo`
(docs/schemas/001_create_tables.sql).

Nota de escopo: os valores abaixo são os que o A5 deve conseguir detectar de
forma AUTOMÁTICA a partir da conversa. A coluna `escalations.motivo` aceita
mais 5 valores que não aparecem nesta lista — 'divergencia_politica_contrato',
'acesso_sem_agendamento', 'despesa_responsabilidade_incerta',
'extensao_informal_fora_condicoes', 'checkout_vistoria_saida'. Presumimos que
esses existem para escalonamento MANUAL feito pela staff via dashboard, não
fazem parte do escopo automático do A5 por ora. Vale confirmar com o Davi se
algum deles deveria entrar na detecção automática também.

Nota de escopo (itens 4 e 5, sublocacao_pedido e troca_fiador): identificados
a partir da leitura direta dos 8 contratos reais, não estavam na lista
original — pendente confirmação com o Domingos sobre se esses fluxos entram
no MVP ou ficam como escopo negativo por ora. Mantidos aqui como
detectáveis; a decisão de negócio (agir ou não sobre eles) é de quem
consome `executar_escalonamento`, não deste módulo.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CriterioEscalonamento:
    motivo: str
    descricao: str
    # False para critérios que NÃO dá pra avaliar Claude só com o texto da
    # mensagem atual — nesse caso o critério é excluído do prompt de
    # avaliar_escalonamento (que só vê uma mensagem por vez) e detectado por
    # outro caminho:
    #   - loop_nao_resolvido / frustracao_crescente: precisam de estado
    #     acumulado da conversa (quantas vezes a mesma dúvida apareceu,
    #     sinais de frustração ao longo do histórico). O design formal disso
    #     (um sinal "resolvido: sim/não" por turno, mantido pelo
    #     orquestrador) ainda não existe — ver detectar_loop_ou_frustracao em
    #     escalonamento.py, que é uma aproximação heurística, não a versão
    #     final.
    #   - atraso_severo: nem depende de mensagem nenhuma — é disparado pelo
    #     cron diário do A2 (ver docs/schemas/009_escalation_atraso_severo.sql),
    #     não por texto de conversa.
    deteccao_via_mensagem: bool = True


CRITERIOS: list[CriterioEscalonamento] = [
    CriterioEscalonamento(
        "sem_clausula",
        "Sem cláusula correspondente no contrato do inquilino para a dúvida levantada.",
    ),
    CriterioEscalonamento(
        "pedido_humano",
        "Pedido explícito de falar com um humano (Fernanda/Domingos/equipe).",
    ),
    CriterioEscalonamento(
        "rescisao_antecipada",
        "Pedido de rescisão antecipada ou aviso de saída do imóvel.",
    ),
    CriterioEscalonamento(
        "desconto_renegociacao",
        "Pedido de desconto, renegociação de valor de aluguel, ou perdão/redução de multa.",
    ),
    CriterioEscalonamento(
        "ameaca_juridica",
        'Menção a advogado, processo judicial, "vou processar" ou Procon.',
    ),
    CriterioEscalonamento(
        "sublocacao_pedido",
        "Pedido de AÇÃO para sublocar, ceder ou transferir o contrato — diferente de só "
        "perguntar se é permitido (isso é dúvida de informação, não precisa escalar sozinha).",
    ),
    CriterioEscalonamento(
        "troca_fiador",
        "Pedido de substituição de fiador (maioria dos contratos: prazo de 30 dias, "
        "aprovação exclusiva da locadora).",
    ),
    CriterioEscalonamento(
        "obito_fiador",
        "Comunicação de óbito, incapacidade ou insolvência do fiador (mesma cláusula/prazo "
        "de troca_fiador).",
    ),
    CriterioEscalonamento(
        "risco_estrutural",
        "Risco estrutural: infiltração grave, fiação exposta, risco de desabamento.",
    ),
    CriterioEscalonamento(
        "emergencia",
        "Emergência que compromete a habitabilidade do imóvel (incêndio, alagamento).",
    ),
    CriterioEscalonamento(
        "terceiros_condominio",
        "Pedido de AÇÃO da gestora contra vizinho ou condomínio — não qualquer menção "
        "passageira a vizinho.",
    ),
    CriterioEscalonamento(
        "loop_nao_resolvido",
        "Mesma dúvida repetida 2 vezes sem resolução.",
        deteccao_via_mensagem=False,
    ),
    CriterioEscalonamento(
        "frustracao_crescente",
        "Sinais de frustração crescente (repetição, tom alterado) ao longo da conversa.",
        deteccao_via_mensagem=False,
    ),
    CriterioEscalonamento(
        "atraso_severo",
        "Inadimplência crônica (D+15) detectada automaticamente pelo cron diário de "
        "cobrança do A2 — aciona a gestão para ação manual. Nunca disparado a partir de "
        "uma mensagem do inquilino.",
        deteccao_via_mensagem=False,
    ),
]

CRITERIOS_POR_MOTIVO: dict[str, CriterioEscalonamento] = {c.motivo: c for c in CRITERIOS}
