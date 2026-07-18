"""Convenção de ID dos botões interativos do A2 (Fernanda confirma/diverge
pelo WhatsApp).

Formato: "{acao}|{contract_id}|{charge_id_ou_lista}" — plano, sem JSON, pra
caber tranquilo no limite de 256 caracteres que a Meta impõe pro campo `id`
de um botão de interactive message. Múltiplos charge_id (caso combinado)
vão separados por vírgula.

Este módulo junta as duas pontas (montar E decodificar) de propósito: quem
for implementar o ENVIO real da interactive message (ainda não existe — ver
notificacao.py, que só loga por enquanto) precisa montar o `id` de cada
botão usando exatamente as funções `montar_button_id_*` daqui, senão o lado
do webhook (decodificar_button_id, usado em
app/orchestrator/processar_mensagem.py) não reconhece o clique.

decodificar_button_id nunca lança — devolve None pra qualquer coisa que não
reconheça, porque um clique de botão que chega maltormado não pode virar uma
exceção não tratada no meio do processamento do webhook.
"""

from dataclasses import dataclass
from typing import Optional

ACAO_CONFIRMAR = "confirmar"
ACAO_DIVERGENTE = "divergente"
ACAO_COMBINADO_TODOS = "combinado_todos"

# "Só uma delas" (pagamento combinado parcial) de propósito NÃO tem suporte
# de decodificação aqui. Ver app/agents/a2_cobranca/comprovante.py,
# docstring de marcar_apenas_uma_paga: um clique de botão sozinho não diz
# QUAL das charges foi de fato paga — falta uma interação adicional
# (provavelmente uma lista de opções ou resposta de texto) que ainda não foi
# desenhada. A constante existe só pra reservar o nome/valor, não pra ser
# produzida ou aceita por este módulo ainda — ver decodificar_button_id.
ACAO_COMBINADO_PARCIAL = "combinado_parcial"

_ACOES_DECODIFICAVEIS = frozenset({ACAO_CONFIRMAR, ACAO_DIVERGENTE, ACAO_COMBINADO_TODOS})

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


@dataclass
class ButtonIdDecodificado:
    acao: str
    contract_id: str
    charge_ids: list[str]


def decodificar_button_id(button_id: str) -> Optional[ButtonIdDecodificado]:
    """None se o formato não for reconhecido (veio de um botão antigo,
    corrompido, ou de combinado_parcial — ainda sem suporte). Quem chama
    deve tratar None como "não consigo processar este clique
    automaticamente, precisa de intervenção manual", nunca como erro fatal."""
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
