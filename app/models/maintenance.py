from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CategoriaManutencao = Literal["hidraulica", "eletrica", "pintura", "estrutural", "outros"]
UrgenciaManutencao = Literal["alta", "media", "baixa"]


class ClassificacaoManutencao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoria: CategoriaManutencao = Field(description="Categoria do problema relatado.")
    urgencia: UrgenciaManutencao = Field(
        description=(
            "alta: risco à segurança ou ao imóvel (ex: vazamento grande, fiação exposta, "
            "porta/fechadura quebrada). media: afeta o uso mas sem risco (ex: chuveiro não "
            "esquenta, torneira pingando). baixa: estético (ex: pintura descascando, rejunte)."
        )
    )
    sinais_risco: list[str] = Field(
        default_factory=list,
        description="Sinais de risco explícitos extraídos do relato (ex: 'vazamento grande', "
        "'fiação exposta', 'fumaça'). Lista vazia se nenhum sinal de risco foi encontrado.",
    )
    justificativa: str = Field(
        description="Explicação curta de por que essa categoria e urgência foram escolhidas."
    )
    categoria_confidence: float = Field(
        ge=0, le=1, description="Confiança do modelo na categoria escolhida, de 0 a 1."
    )
    urgencia_confidence: float = Field(
        ge=0, le=1, description="Confiança do modelo na urgência escolhida, de 0 a 1."
    )


class TicketManutencao(BaseModel):
    """Espelha uma linha de maintenance_tickets após aberta via agent_open_maintenance_ticket."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    protocolo: str
    categoria: CategoriaManutencao
    urgencia: UrgenciaManutencao
    descricao: str
    sinais_risco: list[str] = Field(default_factory=list)
    classificacao_incerta: bool = False
