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
    descricao_formatada: str = Field(
        description="O relato do inquilino reescrito como uma frase objetiva e bem formatada, "
        "em português, pra aparecer no chamado e na notificação da equipe — SEM ruído (saudação, "
        "interjeição tipo 'hein?', repetição) e sem inventar nenhum detalhe que o inquilino não "
        "mencionou. Ex: relato 'a torneira da cozinha esta pingando direto' vira 'Torneira da "
        "cozinha pingando de forma contínua.'."
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
