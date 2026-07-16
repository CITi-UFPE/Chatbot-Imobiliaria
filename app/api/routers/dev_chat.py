"""Chat simulado — ambiente de teste do fluxo completo (webhook -> orquestrador
-> agente -> banco -> resposta) sem depender da conta real do WhatsApp
Business API, que ainda não foi contratada.

Ponto de atenção (o motivo deste módulo existir do jeito que existe): o
payload que este endpoint monta para app.orchestrator.processar_mensagem_recebida
imita a estrutura real do webhook da Meta (simplificada, mas com as mesmas
chaves) — ver _payload_estilo_meta abaixo. Quando a integração real entrar
(Semana 4), a troca é só de FONTE da mensagem (Meta em vez deste formulário);
a função de processamento é literalmente a mesma chamada dos dois lugares,
sem reescrever nada.

Só disponível fora de produção — ver a condição em app/api/main.py que só
inclui este router se ENVIRONMENT != "production". Não expor isso pro
público: qualquer pessoa com a URL poderia mandar mensagem "como se fosse"
qualquer telefone cadastrado.
"""

import time
import uuid

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.orchestrator.processar_mensagem import processar_mensagem_recebida

router = APIRouter(prefix="/dev/chat-simulado", tags=["dev"])


class MensagemSimulada(BaseModel):
    telefone: str  # formato +55DDD9XXXXXXXX, igual à coluna contracts.telefone_whatsapp
    texto: str


def _payload_estilo_meta(telefone: str, texto: str) -> dict:
    """Monta um payload no MESMO formato que o WhatsApp Cloud API manda no
    webhook real (estrutura documentada pela Meta), simplificado para os
    campos que processar_mensagem_recebida realmente lê. É por isso que dá
    para chamar a função de processamento de produção sem adaptação nenhuma."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": f"wamid.simulado-{uuid.uuid4()}",
                                    "from": telefone,
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": texto},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@router.post("/mensagem")
def enviar_mensagem_simulada(msg: MensagemSimulada) -> dict:
    """Processa a mensagem de forma SÍNCRONA (sem BackgroundTasks) para
    devolver a resposta do agente direto pro chat de teste. O webhook real
    (app/api/routers/whatsapp.py) chama a mesma função via BackgroundTasks e
    ignora o retorno; aqui esperamos de propósito, porque o teste precisa
    mostrar a resposta na hora."""
    payload = _payload_estilo_meta(msg.telefone, msg.texto)
    resposta = processar_mensagem_recebida(payload)
    return {"resposta": resposta}


@router.get("/", response_class=HTMLResponse)
def pagina_chat_simulado() -> str:
    return _HTML_CHAT


_HTML_CHAT = """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Chat simulado — teste do fluxo A1-A5</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.1rem; }
  .aviso { background: #fff3cd; border: 1px solid #ffe69c; padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.85rem; margin-bottom: 1rem; }
  #telefone { width: 100%; padding: 0.5rem; margin-bottom: 1rem; box-sizing: border-box; }
  #historico { border: 1px solid #ccc; border-radius: 6px; padding: 0.75rem; height: 400px; overflow-y: auto; margin-bottom: 1rem; background: #fafafa; }
  .msg { margin-bottom: 0.6rem; padding: 0.5rem 0.75rem; border-radius: 8px; max-width: 80%; white-space: pre-wrap; }
  .inquilino { background: #d1e7ff; margin-left: auto; text-align: right; }
  .agente { background: #e2e2e2; }
  .erro { background: #f8d7da; }
  .linha-input { display: flex; gap: 0.5rem; }
  #texto { flex: 1; padding: 0.5rem; }
  button { padding: 0.5rem 1rem; }
</style>
</head>
<body>
  <h1>Chat simulado — teste do fluxo webhook &rarr; orquestrador &rarr; agente &rarr; banco</h1>
  <div class="aviso">
    Ferramenta de dev, não é a interface final. Só funciona pra um telefone que já
    exista em <code>contracts.telefone_whatsapp</code> com <code>status='ativo'</code>.
  </div>
  <input id="telefone" type="text" placeholder="+5581999999999 (telefone do contrato de teste)">
  <div id="historico"></div>
  <div class="linha-input">
    <input id="texto" type="text" placeholder="Digite a mensagem do inquilino...">
    <button onclick="enviar()">Enviar</button>
  </div>

<script>
async function enviar() {
  const telefone = document.getElementById('telefone').value.trim();
  const texto = document.getElementById('texto').value.trim();
  if (!telefone || !texto) { alert('Preencha telefone e mensagem.'); return; }

  adicionarMensagem('inquilino', texto);
  document.getElementById('texto').value = '';

  try {
    const resp = await fetch('/dev/chat-simulado/mensagem', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ telefone, texto }),
    });
    const dados = await resp.json();
    if (dados.resposta) {
      adicionarMensagem('agente', dados.resposta);
    } else {
      adicionarMensagem('erro', '(sem resposta — verifique os logs do backend)');
    }
  } catch (e) {
    adicionarMensagem('erro', 'Erro de rede: ' + e);
  }
}

function adicionarMensagem(tipo, texto) {
  const historico = document.getElementById('historico');
  const div = document.createElement('div');
  div.className = 'msg ' + tipo;
  div.textContent = texto;
  historico.appendChild(div);
  historico.scrollTop = historico.scrollHeight;
}

document.getElementById('texto').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') enviar();
});
</script>
</body>
</html>
"""
