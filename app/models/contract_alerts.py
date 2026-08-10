from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IndiceReajuste = Literal["igpm", "ipca", "livre_negociacao"]
TipoAlerta = Literal["alerta_renovacao_d60", "calculo_reajuste_d30"]
DecisaoGestora = Literal["pendente", "renovar_sugerido", "renovar_ajustado", "encerrar"]
TipoRenovacao = Literal[
    "novo_contrato", "requer_aditivo", "automatica", "indeterminado_por_lei", "nao_identificado"
]


class ContratoParaAlerta(BaseModel):
    """Espelha o retorno de cron_listar_contratos_ativos (migration 010,
    ajustada nas migrations 013 e 016)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    imovel_identificacao: str
    inquilino_nome: str
    telefone_whatsapp: str
    data_inicio: date
    data_termino: date
    indice_reajuste: Optional[IndiceReajuste] = None
    valor_aluguel: float = Field(gt=0)
    prazo_indeterminado: bool = False
    tipo_renovacao: TipoRenovacao = "novo_contrato"