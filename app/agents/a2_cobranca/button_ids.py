"""Convenção de ID dos botões interativos do A2 (Fernanda confirma/diverge
pelo WhatsApp).

Formato: "{acao}|{contract_id}|{charge_id_ou_lista}" — plano, sem JSON, pra
caber tranquilo no limite de 256 caracteres que a Meta impõe pro campo `id`
de um botão de interactive message. Múltiplos charge_id (caso combinado)
vão separados por vírgula.

Este módulo junta as duas pontas (montar E decodificar) de propósito: quem
for implementar o ENVIO real da interactive message precisa montar o `id`
de cada botão usando exatamente as funções `montar_button_id_*` daqui,
senão o lado do webhook (decodificar_button_id, usado em
app/orchestrator/orchestrator.py::rotear_clique_botao_a2) não reconhece o
clique.

decodificar_button_id nunca lança — devolve None pra qualquer coisa que não
reconheça, porque um clique de botão que chega maltormado não pode virar uma
exceção não tratada no meio do processamento do webhook.

Compatibilidade com pagamento combinado parcial antigo ("Só uma delas") —
fluxo em DUAS etapas, porque
um clique sozinho nunca diz QUAL charge foi de fato paga:

  1. ACAO_ESCOLHER_PARCIAL: primeiro clique ("Só uma delas" na mensagem
     original de pagamento combinado). Carrega só contract_id + TODAS as
     charge_ids envolvidas — ainda não sabe qual foi paga. Decodificado,
     dispara uma SEGUNDA mensagem com um botão por charge (ver
     app/agents/a2_cobranca/comprovante.py::iniciar_escolha_pagamento_parcial
     e notificacao.py::notificar_pergunta_qual_charge_paga).
  2. ACAO_COMBINADO_PARCIAL: segundo clique, um por charge possível (ex:
     "Aluguel" / "Água"). O charge_id do botão clicado vem SEMPRE primeiro
     na lista de charge_ids; os demais (que voltam pra 'pendente') vêm
     depois — convenção que montar_button_id_combinado_parcial já garante.
"""

from dataclasses import dataclass
from typing import Optional

ACAO_CONFIRMAR = "confirmar"
ACAO_DIVERGENTE = "divergente"
ACAO_COMBINADO_TODOS = "combinado_todos"
ACAO_ESCOLHER_PARCIAL = "escolher_parcial"
ACAO_COMBINADO_PARCIAL = "combinado_parcial"

_ACOES_DECODIFICAVEIS = frozenset(
    {
        ACAO_CONFIRMAR,
        ACAO_DIVERGENTE,
        ACAO_COMBINADO_TODOS,
        ACAO_ESCOLHER_PARCIAL,
        ACAO_COMBINADO_PARCIAL,
    }
)

_SEPARADOR_CAMPO = "|"
_SEPARADOR_LISTA = ","


def montar_button_id_confirmar(contract_id: str, charge_id: str) -> str:
    return _SEPARADOR_CAMPO.join([ACAO_CONFIRMAR, contract_id, charge_id])


def montar_button_id_divergente(contract_id: str, charge_id: str) -> str:
    return _SEPARADOR_CAMPO.join([ACAO_DIVERGENTE, contract_id, charge_id])


def montar_button_id_combinado_todos(contract_id: str, charge_ids: list[str]) -> str:
    return _SEPARADOR_CAMPO.join(
        [ACAO_COMBINADO_TODOS, contract_id, _SEPARADOR_LISTA.join(charge_ids)]
    )


def montar_button_id_escolher_parcial(contract_id: str, charge_ids: list[str]) -> str:
    """ID legado para botões "Só uma delas" já enviados.

    Mensagens novas usam `montar_button_id_combinado_parcial` diretamente,
    mas este construtor e sua decodificação permanecem durante a transição.
    """
    return _SEPARADOR_CAMPO.join(
        [ACAO_ESCOLHER_PARCIAL, contract_id, _SEPARADOR_LISTA.join(charge_ids)]
    )


def montar_button_id_combinado_parcial(
    contract_id: str, charge_id_paga: str, charge_ids_restantes: list[str]
) -> str:
    """Botão de UMA charge específica na 2ª etapa (ex: "Aluguel"). O
    charge_id_paga sempre vai PRIMEIRO na lista codificada — é assim que
    decodificar_button_id sabe distinguir "a que foi paga" das "que voltam
    pra pendente" sem precisar de um separador a mais no formato."""
    todos = [charge_id_paga, *charge_ids_restantes]
    return _SEPARADOR_CAMPO.join([ACAO_COMBINADO_PARCIAL, contract_id, _SEPARADOR_LISTA.join(todos)])


@dataclass
class ButtonIdDecodificado:
    acao: str
    contract_id: str
    charge_ids: list[str]


def decodificar_button_id(button_id: str) -> Optional[ButtonIdDecodificado]:
    """None se o formato não for reconhecido (veio de um botão antigo ou
    corrompido). Quem chama deve tratar None como "não consigo processar
    este clique automaticamente, precisa de intervenção manual", nunca
    como erro fatal."""
    if not button_id:
        return None

    partes = button_id.split(_SEPARADOR_CAMPO)
    if len(partes) != 3:
        return None

    acao, contract_id, charge_ids_str = partes
    if acao not in _ACOES_DECODIFICAVEIS:
        return None
    if not contract_id or not charge_ids_str:
        return None

    return ButtonIdDecodificado(
        acao=acao,
        contract_id=contract_id,
        charge_ids=charge_ids_str.split(_SEPARADOR_LISTA),
    )
