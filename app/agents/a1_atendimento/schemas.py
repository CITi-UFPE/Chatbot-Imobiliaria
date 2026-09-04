"""Schemas de dados do Agente 1 — Atendimento ao Inquilino.

Espelham exatamente o que as RPCs buscar_dados_inquilino e
consultar_historico devolvem (ver docs/schemas/006_a1_rpcs.sql),
que por sua vez espelham as colunas reais de `contracts`, `contract_clauses`,
`maintenance_tickets`, `charge_negotiations` e `escalations`
(docs/schemas/001_create_tables.sql).

Usados para validar o retorno do Supabase ANTES de repassar pro Claude como
tool_result — se o formato do RPC mudar no banco sem avisar aqui, isso deve
quebrar nesta camada, não virar um campo estranho que o modelo tenta
interpretar sozinho.

Nota: a Migration 001 criou `contract_clauses.categoria` com só 9 valores,
mas a Migration 003 ampliou o constraint pra 12 (adicionou prazo_vigencia,
alienacao, disposicoes_gerais), alinhando com o CategoriaClausula usado na
extração do contrato. O enum abaixo já reflete os 12 valores vigentes.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CategoriaClausulaContrato = Literal[
    "financeiro",
    "benfeitorias",
    "sublocacao",
    "vistoria",
    "conservacao",
    "agua_energia",
    "fiador",
    "rescisao",
    "multa",
    "prazo_vigencia",
    "alienacao",
    "disposicoes_gerais",
]


class ClausulaContrato(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero_clausula: str = Field(description="Identificador da cláusula tal como no contrato (ex: '5', '5.2').")
    titulo_clausula: str = Field(description="Título/assunto da cláusula.")
    texto_clausula: str = Field(
        description="Texto original da cláusula. O A1 deve PARAFRASEAR isso ao responder o "
        "inquilino, não colar o texto jurídico bruto na conversa de WhatsApp."
    )
    categoria: CategoriaClausulaContrato


class DadosInquilino(BaseModel):
    """Retorno esperado da RPC `buscar_dados_inquilino` (sem parâmetros —
    o contrato é resolvido internamente via agent_contract_id())."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str
    tipo_locatario: Literal["pf", "pj"]
    inquilino_nome: str
    # Só populado na prática quando tipo_locatario == "pj". Não existe no
    # banco nenhum campo que diga "quem manda mensagem agora tem autoridade
    # pra decidir" — a única trava de identidade é telefone_whatsapp ser
    # único por contrato ativo (constraint contracts_telefone_ativo_uidx).
    responsavel_contato_nome: Optional[str] = None
    valor_aluguel: float
    dia_vencimento: int = Field(ge=1, le=31)
    vencimento_mes_referencia: Literal["atual", "anterior"]
    data_inicio: str
    data_termino: str
    indice_reajuste: Optional[Literal["igpm", "ipca", "livre_negociacao"]] = None
    data_aniversario_reajuste: Optional[str] = None
    garantia_tipo: Literal["fiador", "caucao", "aluguel_antecipado"]
    garantia_valor: Optional[float] = None
    fiador_nome: Optional[str] = None
    multa_infracao_tipo: Literal["meses_aluguel", "percentual_valor_anual"]
    multa_infracao_valor: float
    multa_moratoria_percentual: Optional[float] = None
    juros_moratorio_mensal: float
    aviso_previo_dias: int
    aviso_previo_a_partir_mes: int
    imovel_identificacao: str
    imovel_endereco: str
    # Adicionados na Migration 013 — reverte a exclusão original da
    # Migration 006 ("dados bancários são escopo do A2"), porque o A2 nunca
    # respondeu por texto e isso deixava "qual a chave Pix?" sem resposta em
    # lugar nenhum do sistema. CPF/CNPJ do inquilino e do fiador continuam
    # de fora — essa parte da decisão original não mudou.
    banco_agencia: Optional[str] = None
    banco_conta: Optional[str] = None
    pix_chave: Optional[str] = None
    clausulas: list[ClausulaContrato] = Field(default_factory=list)


class RegistroHistorico(BaseModel):
    """Um item do retorno da RPC `consultar_historico` — resultado de um
    UNION ALL entre maintenance_tickets, charge_negotiations e escalations,
    já normalizado pro mesmo formato dentro da própria função SQL."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: Literal["manutencao", "cobranca", "escalonamento"]
    status: str
    resumo: str
    criado_em: str


# --- Status de cobrança (Migration 023 — buscar_status_cobranca_inquilino) --
#
# TipoCobranca/StatusCharge duplicam de propósito os equivalentes em
# app/agents/a2_cobranca/schemas.py (mesmos valores, mesma origem: a check
# constraint de `charges` na Migration 001) — cada agente fica isolado do
# domínio do outro, mesmo espírito de CategoriaClausulaContrato acima não
# ser importado de lugar nenhum. Nunca importar deste módulo para o A2 nem
# o contrário.

TipoCobranca = Literal["aluguel", "agua"]
StatusCharge = Literal[
    "pendente", "aguardando_confirmacao", "confirmado", "divergente",
    "atrasado", "em_negociacao", "quitado",
]


class ChargeEmAberto(BaseModel):
    """Uma cobrança do contrato ainda não paga/confirmada — qualquer status
    diferente de 'confirmado'/'quitado'. Espelha um item de
    `charges_abertas` no retorno de `buscar_status_cobranca_inquilino`
    (ver docs/schemas/023_status_cobranca_a1.sql)."""

    model_config = ConfigDict(extra="forbid")

    charge_id: str
    tipo: TipoCobranca
    mes_referencia: str
    valor_esperado: float
    data_vencimento: str
    dias_atraso: int
    status: StatusCharge


class ChargePagaRecente(BaseModel):
    """Uma cobrança com pagamento identificado (`data_pagamento` != null)
    nos ÚLTIMOS 30 DIAS — a janela já vem filtrada pela própria RPC no
    banco, não é uma lista completa de pagamentos. Ver o aviso
    correspondente no SYSTEM_PROMPT de atendimento.py."""

    model_config = ConfigDict(extra="forbid")

    charge_id: str
    tipo: TipoCobranca
    mes_referencia: str
    valor_esperado: float
    valor_identificado: Optional[float] = None
    data_pagamento: str
    status: StatusCharge


class StatusCobrancaContrato(BaseModel):
    """Retorno esperado da RPC `buscar_status_cobranca_inquilino` (sem
    parâmetros — o contrato é resolvido internamente via
    agent_contract_id(), mesmo padrão de DadosInquilino acima)."""

    model_config = ConfigDict(extra="forbid")

    charges_abertas: list[ChargeEmAberto] = Field(default_factory=list)
    charges_pagas_ultimos_30_dias: list[ChargePagaRecente] = Field(default_factory=list)