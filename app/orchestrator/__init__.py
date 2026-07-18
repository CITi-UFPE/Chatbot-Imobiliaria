"""Pacote app.orchestrator.

agent_auth e classificador são módulos-folha (não importam nenhum
app.agents.*) — seguros pra importar aqui em cima, no carregamento do
pacote. rotear_mensagem e processar_mensagem_recebida, ao contrário,
arrastam transitivamente TODOS os agentes (A1-A5): orchestrator.py importa
a1_atendimento/a3_manutencao/a5_escalonamento, e processar_mensagem.py
importa orchestrator.py.

Isso importa porque vários módulos de agente (ex:
app/agents/a5_escalonamento/escalonamento.py,
app/agents/a1_atendimento/atendimento.py) fazem
`from app.orchestrator.agent_auth import obter_client_agente` — e importar
QUALQUER submódulo de um pacote obriga o Python a rodar o __init__.py do
pacote inteiro primeiro. Se esse __init__.py importasse rotear_mensagem
sempre (como fazia antes), qualquer módulo que importasse
app.agents.a5_escalonamento (ou algo que dependa dele) ANTES de tocar em
app.orchestrator acabaria, indiretamente, pedindo pro Python reimportar
app.agents.a5_escalonamento no meio da própria inicialização dele —
"cannot import name ... from partially initialized module" (ImportError de
import circular). Foi exatamente o que aconteceu com
app/agents/a2_cobranca/cobranca.py (importa a5_escalonamento antes de
agent_auth) — funcionava por acidente nos outros agentes só porque nenhum
deles disparava esse caminho primeiro.

Fix: rotear_mensagem/processar_mensagem_recebida viram import tardio via
__getattr__ (PEP 562) — só carregam de fato no primeiro uso via
`from app.orchestrator import rotear_mensagem`, não no carregamento do
pacote. Nenhum consumidor real do projeto usa esse caminho hoje (todos
importam do submódulo direto, ex: `from app.orchestrator.orchestrator
import rotear_mensagem`), então isso não muda nada pra ninguém — só remove
o gatilho do ciclo.
"""

from app.orchestrator.agent_auth import (
    assinar_token_agente,
    assinar_token_cron_batch,
    obter_client_agente,
    obter_client_cron_batch,
)
from app.orchestrator.classificador import ClassificacaoIntencao, classificar_intencao

__all__ = [
    "assinar_token_agente",
    "obter_client_agente",
    "assinar_token_cron_batch",
    "obter_client_cron_batch",
    "ClassificacaoIntencao",
    "classificar_intencao",
    "rotear_mensagem",
    "processar_mensagem_recebida",
]


def __getattr__(name: str):
    if name == "rotear_mensagem":
        from app.orchestrator.orchestrator import rotear_mensagem

        return rotear_mensagem
    if name == "processar_mensagem_recebida":
        from app.orchestrator.processar_mensagem import processar_mensagem_recebida

        return processar_mensagem_recebida
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
