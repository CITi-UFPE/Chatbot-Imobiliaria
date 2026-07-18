"""Schemas de dados do Agente 2 — Cobrança e Inadimplência.

Espelham o que as RPCs devolvem: cron_listar_charges_ativas (Migration 008,
cross-contrato, só campos operacionais) e buscar_dados_cobranca_contrato
(Migration 011, escopada por contrato, dado pessoal + parâmetros de
encargo).
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EstagioCobranca = Literal["d-5", "d0", "d+5", "d+10", "d+15"]
TipoCobranca = Literal["aluguel", "agua"]
StatusCharge = Literal[
    "pendente", "aguardando_confirmacao", "confirmado", "divergente",
    "atrasado", "em_negociacao", "quitado",
]


class ChargeAtiva(BaseModel):
    """Uma linha do retorno de cron_listar_charges_ativas — cross-contrato,
    sem dado pessoal nenhum de propósito (ver Migration 008)."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str
    charge_id: str
    tipo: TipoCobranca
    mes_referencia: date
    valor_esperado: float
    data_vencimento: date
    data_pagamento: Optional[date] = None
    dias_atraso: int
    status: StatusCharge
    mensagem_estagio: Optional[EstagioCobranca] = None


class DadosCobrancaContrato(BaseModel):
    """Retorno de buscar_dados_cobranca_contrato — escopado por contrato,
    buscado só DEPOIS de cron_listar_charges_ativas já ter identificado que
    esse contrato precisa de ação hoje."""

    model_config = ConfigDict(extra="forbid")

    telefone_whatsapp: str
    inquilino_nome: str
    imovel_identificacao: str
    # Nullable no banco — contrato incompleto/pendente_confirmacao pode não
    # ter isso preenchido ainda. Ver nota de unidade em Migration 011: este
    # código assume fração (0.02 = 2%), igual juros_moratorio_mensal — não
    # confirmado contra dado real ainda.
    multa_moratoria_percentual: Optional[float] = None
    juros_moratorio_mensal: float = 0.01


class ComprovanteExtraido(BaseModel):
    """Retorno da extração por visão de um comprovante de pagamento
    (ver comprovante.py). Sempre extraído via tool forçada (tool_choice
    explícito, não "auto") — queremos SEMPRE uma tentativa de extração
    estruturada, nunca o modelo respondendo em texto livre sobre a imagem."""

    model_config = ConfigDict(extra="forbid")

    valor_identificado: Optional[float] = Field(
        default=None, description="Valor do pagamento identificado no comprovante, se legível."
    )
    data_identificada: Optional[str] = Field(
        default=None,
        description="Data do pagamento identificada no comprovante, normalizada para o "
        "formato ISO 8601 (YYYY-MM-DD). Se a data não estiver legível ou não puder ser "
        "determinada com confiança (ex: ano ambíguo, imagem cortada), deixe null em vez "
        "de arriscar um formato ou valor incerto — isso vai direto para uma coluna 'date' "
        "no banco, não aceita texto livre.",
    )
    beneficiario_identificado: Optional[str] = Field(
        default=None, description="Nome do beneficiário/favorecido identificado no comprovante, se legível."
    )
    legivel: bool = Field(
        description="False se a imagem estiver ilegível, cortada, ou não parecer um comprovante de pagamento."
    )
    observacoes: Optional[str] = Field(
        default=None, description="Qualquer ambiguidade ou detalhe relevante encontrado na leitura."
    )