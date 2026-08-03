from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ContratoParaMatch(BaseModel):
    """Contrato ativo enviado pelo frontend para a IA usar na correspondência.
    Espelha só os 3 campos que o fluxo híbrido precisa (id, imovel_identificacao,
    imovel_endereco) — não é o contrato inteiro."""

    id: str
    imovel_identificacao: str
    imovel_endereco: str


class CandidatoContratoAgua(BaseModel):
    """Um contrato candidato devolvido pela IA, com grau de confiança e
    justificativa. Serializado em camelCase pro frontend (mesmo padrão de
    ExtracaoContaAguaResult abaixo) — e é esse mesmo JSON Schema (via
    model_json_schema) que vira o input_schema da tool enviada à Claude, então
    as descriptions abaixo são instrução direta pro modelo, não só documentação."""

    model_config = ConfigDict(populate_by_name=True)

    contract_id: str = Field(
        alias="contractId",
        description="id do contrato candidato, copiado exatamente da lista de contratos recebida",
    )
    confianca: float = Field(description="Grau de confiança da correspondência, de 0 a 1")
    justificativa: str = Field(
        description="Breve explicação do porquê esse contrato corresponder (ou não) ao documento"
    )


class ExtracaoContaAguaResult(BaseModel):
    """Formato retornado pelo agente de extração+correspondência
    (app/tools/water_bill_extraction.py). Ao contrário do ExtracaoContratoResult
    de contratos, aqui os campos não espelham uma tabela do banco 1:1 — são só
    os dados lidos do PDF da conta de água, exibidos na tela de conferência
    antes de virar um registro em `charges`. Por isso os nomes ficam em
    camelCase, combinando com a interface TS do frontend (AguaSection.tsx)."""

    model_config = ConfigDict(populate_by_name=True)

    condominio: str = Field(description="Nome do condomínio/edifício como aparece no documento")
    apartamento: str = Field(description="Número do apartamento")
    bloco: str | None = Field(default=None, description="Bloco, se houver; null caso contrário")
    periodo_inicio: str = Field(
        alias="periodoInicio", description="Início do período de consumo, formato YYYY-MM-DD"
    )
    periodo_fim: str = Field(
        alias="periodoFim", description="Fim do período de consumo, formato YYYY-MM-DD"
    )
    valor_total: Decimal = Field(alias="valorTotal", description="Valor total a pagar")
    candidatos: list[CandidatoContratoAgua] = Field(
        default_factory=list,
        description=(
            "Contratos candidatos ao imóvel do documento, ordenados do mais "
            "provável ao menos provável. Lista vazia se nenhum contrato "
            "corresponder com confiança razoável."
        ),
    )