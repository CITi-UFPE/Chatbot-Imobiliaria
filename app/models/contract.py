from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

CategoriaClausula = Literal[
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


class ClausulaExtraida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero_clausula: str = Field(
        description="Número ou identificador da cláusula tal como aparece no contrato (ex: '5', '5.2')."
    )
    titulo_clausula: str = Field(description="Título ou assunto da cláusula.")
    texto_clausula: str = Field(
        description="Texto original da cláusula, transcrito do contrato — não resumir nem parafrasear."
    )
    categoria: CategoriaClausula = Field(
        description=(
            "Categoria que melhor classifica o assunto da cláusula:\n"
            "- financeiro: valor do aluguel, reajuste, índice de correção, tributos (IPTU) "
            "e forma/local de pagamento.\n"
            "- benfeitorias: obras, reformas ou melhorias no imóvel feitas pelo locatário.\n"
            "- sublocacao: cessão, empréstimo ou sublocação do imóvel a terceiros.\n"
            "- vistoria: inspeção do imóvel, visitas da locadora ou de interessados, termo de vistoria.\n"
            "- conservacao: estado de conservação, limpeza, manutenção e devolução do imóvel "
            "nas condições em que foi recebido.\n"
            "- agua_energia: consumo e transferência de contas de água e energia elétrica.\n"
            "- fiador: obrigações, renúncias e substituição do fiador.\n"
            "- multa: penalidades por mora (atraso de pagamento) ou por infração contratual.\n"
            "- rescisao: rescisão de fato — quebra ou término antecipado do contrato por "
            "qualquer parte, incluindo desapropriação e outras causas de extinção do contrato.\n"
            "- prazo_vigencia: duração do contrato, prorrogação e permanência do locatário no "
            "imóvel após o término do prazo (holdover).\n"
            "- alienacao: direito de preferência do locatário e regras aplicáveis caso o "
            "imóvel seja vendido durante a locação.\n"
            "- disposicoes_gerais: categoria residual para cláusulas que não se encaixem "
            "claramente em nenhuma categoria acima (ex: objeto do contrato, foro de eleição, "
            "forma de citação/notificação, estipulações finais)."
        )
    )


class ContratoExtraido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imovel_identificacao: str = Field(
        description="Identificação do imóvel (ex: 'Apto 2702, Golden Beach')."
    )
    imovel_endereco: str = Field(description="Endereço completo do imóvel.")
    tipo_locatario: Literal["pf", "pj"] = Field(
        description="'pf' se o inquilino é pessoa física, 'pj' se é pessoa jurídica."
    )
    inquilino_nome: str = Field(
        description="Nome do inquilino (ou razão social, se tipo_locatario='pj')."
    )
    inquilino_cpf_cnpj: str = Field(description="CPF do inquilino ou CNPJ da empresa.")
    locatario_endereco: Optional[str] = Field(
        default=None,
        description="Endereço residencial do locatário (não confundir com imovel_endereco, "
        "que é o endereço do imóvel alugado) — usado para notificação formal.",
    )
    responsavel_contato_nome: Optional[str] = Field(
        default=None,
        description="Nome do responsável pelo contato, quando o locatário é pessoa jurídica.",
    )
    fiador_nome: Optional[str] = Field(default=None, description="Nome do fiador, se houver.")
    fiador_cpf: Optional[str] = Field(default=None, description="CPF do fiador, se houver.")
    fiador_endereco: Optional[str] = Field(
        default=None, description="Endereço residencial do fiador, se houver fiador."
    )
    garantia_tipo: Literal["fiador", "caucao"] = Field(
        description="Tipo de garantia locatícia usada no contrato."
    )
    garantia_valor: Optional[float] = Field(
        default=None, description="Valor da caução, obrigatório quando garantia_tipo='caucao'."
    )
    valor_aluguel: float = Field(description="Valor mensal do aluguel.", gt=0)
    dia_vencimento: int = Field(description="Dia do mês em que o aluguel vence.", ge=1, le=31)
    vencimento_mes_referencia: Literal["atual", "anterior"] = Field(
        default="atual",
        description="Se o vencimento se refere ao mês atual ou ao mês anterior de uso do imóvel.",
    )
    data_inicio: date = Field(description="Data de início do contrato.")
    data_termino: date = Field(description="Data de término do contrato.")
    indice_reajuste: Optional[Literal["igpm", "livre_negociacao"]] = Field(
        default=None, description="Índice usado para reajuste anual do aluguel, se especificado."
    )
    data_aniversario_reajuste: Optional[date] = Field(
        default=None, description="Data-base do reajuste anual, quando houver um dia fixo definido."
    )
    multa_infracao_tipo: Literal["meses_aluguel", "percentual_valor_anual"] = Field(
        description="Como a multa por infração contratual é calculada."
    )
    multa_infracao_valor: float = Field(
        description="Valor da multa por infração (nº de meses de aluguel, ou percentual do valor anual).",
        gt=0,
    )
    multa_moratoria_percentual: Optional[float] = Field(
        default=None, description="Percentual de multa por atraso no pagamento, se especificado."
    )
    juros_moratorio_mensal: float = Field(
        default=0.01, description="Percentual de juros de mora ao mês (padrão 1% = 0.01)."
    )
    aviso_previo_dias: int = Field(description="Prazo de aviso prévio para rescisão, em dias.")
    aviso_previo_a_partir_mes: int = Field(
        description="A partir de qual mês de contrato o aviso prévio passa a valer."
    )
    banco_agencia: Optional[str] = Field(default=None, description="Agência bancária para pagamento.")
    banco_conta: Optional[str] = Field(default=None, description="Conta bancária para pagamento.")
    pix_chave: Optional[str] = Field(default=None, description="Chave PIX para pagamento, se informada.")
    observacoes: Optional[str] = Field(
        default=None,
        description="Qualquer informação relevante do contrato que não se encaixe nos demais campos, "
        "ou ambiguidades encontradas durante a extração.",
    )

    @model_validator(mode="after")
    def valida_garantia(self) -> "ContratoExtraido":
        if self.garantia_tipo == "fiador" and (not self.fiador_nome or not self.fiador_cpf):
            raise ValueError("garantia_tipo='fiador' requer fiador_nome e fiador_cpf preenchidos")
        if self.garantia_tipo == "caucao" and self.garantia_valor is None:
            raise ValueError("garantia_tipo='caucao' requer garantia_valor preenchido")
        return self

    @model_validator(mode="after")
    def valida_periodo(self) -> "ContratoExtraido":
        if self.data_termino <= self.data_inicio:
            raise ValueError("data_termino deve ser posterior a data_inicio")
        return self


class ExtracaoContratoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contrato: ContratoExtraido
    clausulas: list[ClausulaExtraida] = Field(default_factory=list)
