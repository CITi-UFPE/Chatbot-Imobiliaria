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

Três formas de simular uma mensagem (ver MensagemSimulada): texto (fluxo
A1/A3/A5), imagem/PDF em base64 (comprovante — A2, ver
app/agents/a2_cobranca/comprovante.py) e clique de botão (decisão da
Fernanda — A2, ver app/agents/a2_cobranca/button_ids.py). O campo
"_dados_base64" dentro do objeto de mídia do payload simulado NÃO existe no
payload real da Meta — é um atalho só deste simulador pra não precisar
implementar o download real de mídia (que exige WHATSAPP_ACCESS_TOKEN, ver
app/orchestrator/processar_mensagem.py::_baixar_midia_whatsapp) só pra
testar local.

Só disponível fora de produção — ver a condição em app/api/main.py que só
inclui este router se ENVIRONMENT != "production". Não expor isso pro
público: qualquer pessoa com a URL poderia mandar mensagem "como se fosse"
qualquer telefone cadastrado, ou simular qualquer clique de botão da
Fernanda pra qualquer contrato.
"""

import time
import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, model_validator

from app.orchestrator.processar_mensagem import processar_mensagem_recebida

router = APIRouter(prefix="/dev/chat-simulado", tags=["dev"])


class MensagemSimulada(BaseModel):
    telefone: str  # formato +55DDD9XXXXXXXX, igual à coluna contracts.telefone_whatsapp
    # inquilino (fluxo de texto padrão). Pra simulação de clique de botão da
    # Fernanda, o telefone não é usado pra resolver contrato nenhum — pode
    # ser qualquer valor, só precisa estar presente no payload.
    texto: Optional[str] = None

    # Comprovante (A2) — mutuamente exclusivo com texto/button_id.
    imagem_base64: Optional[str] = None
    media_type: Optional[str] = None

    # Clique de botão da Fernanda (A2) — mutuamente exclusivo com
    # texto/imagem_base64. Ver app/agents/a2_cobranca/button_ids.py pro
    # formato ("acao|contract_id|charge_id[,charge_id2]").
    button_id: Optional[str] = None

    @model_validator(mode="after")
    def _exatamente_um_tipo(self) -> "MensagemSimulada":
        preenchidos = sum(
            1
            for v in (self.texto, self.imagem_base64, self.button_id)
            if v
        )
        if preenchidos != 1:
            raise ValueError(
                "Informe exatamente um dos três: texto, imagem_base64 (+ media_type) ou button_id."
            )
        if self.imagem_base64 and not self.media_type:
            raise ValueError("imagem_base64 exige media_type (ex: 'image/jpeg', 'application/pdf').")
        return self


def _payload_estilo_meta(msg: MensagemSimulada) -> dict:
    """Monta um payload no MESMO formato que o WhatsApp Cloud API manda no
    webhook real (estrutura documentada pela Meta), simplificado para os
    campos que processar_mensagem_recebida realmente lê. É por isso que dá
    para chamar a função de processamento de produção sem adaptação nenhuma
    — a única exceção é o campo "_dados_base64" (ver docstring do módulo)."""
    mensagem: dict = {
        "id": f"wamid.simulado-{uuid.uuid4()}",
        "from": msg.telefone,
        "timestamp": str(int(time.time())),
    }

    if msg.button_id:
        mensagem["type"] = "interactive"
        mensagem["interactive"] = {
            "type": "button_reply",
            "button_reply": {"id": msg.button_id, "title": msg.button_id},
        }
    elif msg.imagem_base64:
        tipo_midia = "document" if (msg.media_type or "").startswith("application/") else "image"
        mensagem["type"] = tipo_midia
        mensagem[tipo_midia] = {
            "mime_type": msg.media_type,
            "_dados_base64": msg.imagem_base64,  # atalho só do simulador, ver docstring do módulo
        }
    else:
        mensagem["type"] = "text"
        mensagem["text"] = {"body": msg.texto or ""}

    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


@router.post("/mensagem")
def enviar_mensagem_simulada(msg: MensagemSimulada) -> dict:
    """Processa a mensagem de forma SÍNCRONA (sem BackgroundTasks) para
    devolver a resposta do agente direto pro chat de teste. O webhook real
    (app/api/routers/whatsapp.py) chama a mesma função via BackgroundTasks e
    ignora o retorno; aqui esperamos de propósito, porque o teste precisa
    mostrar a resposta na hora."""
    payload = _payload_estilo_meta(msg)
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
  h2 { font-size: 0.95rem; margin-top: 1.5rem; }
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
  .caixa { border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem; margin-bottom: 1rem; }
  .caixa label { display: block; font-size: 0.8rem; color: #555; margin-bottom: 0.25rem; }
  .caixa input, .caixa select { width: 100%; padding: 0.4rem; margin-bottom: 0.5rem; box-sizing: border-box; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
</style>
</head>
<body>
  <h1>Chat simulado — teste do fluxo webhook &rarr; orquestrador &rarr; agente &rarr; banco</h1>
  <div class="aviso">
    Ferramenta de dev, não é a interface final. Pra texto/comprovante, use um telefone que já
    exista em <code>contracts.telefone_whatsapp</code> com <code>status='ativo'</code>. Pra
    clique de botão, o telefone não importa (não é resolvido como contrato).
  </div>
  <input id="telefone" type="text" placeholder="+5581999999999 (telefone do contrato de teste)">
  <div id="historico"></div>
  <div class="linha-input">
    <input id="texto" type="text" placeholder="Digite a mensagem do inquilino...">
    <button onclick="enviarTexto()">Enviar</button>
  </div>

  <h2>Simular comprovante (A2)</h2>
  <div class="caixa">
    <label>Arquivo (imagem ou PDF)</label>
    <input id="arquivo" type="file" accept="image/*,application/pdf">
    <button onclick="enviarComprovante()">Enviar comprovante</button>
  </div>

  <h2>Simular clique de botão da Fernanda (A2)</h2>
  <div class="caixa">
    <label>Ação</label>
    <select id="acaoBotao">
      <option value="confirmar">Confirmar</option>
      <option value="divergente">Valor diverge</option>
      <option value="combinado_todos">Cobre os dois (pagamento combinado)</option>
    </select>
    <div class="grid2">
      <div>
        <label>contract_id</label>
        <input id="contractIdBotao" type="text" placeholder="uuid do contrato">
      </div>
      <div>
        <label>charge_id(s) (separados por vírgula se combinado)</label>
        <input id="chargeIdsBotao" type="text" placeholder="uuid da charge">
      </div>
    </div>
    <button onclick="enviarClique()">Simular clique</button>
  </div>

<script>
async function postMensagem(body) {
  const resp = await fetch('/dev/chat-simulado/mensagem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const dados = await resp.json();
  if (dados.resposta) {
    adicionarMensagem('agente', dados.resposta);
  } else {
    adicionarMensagem('erro', '(sem resposta — verifique os logs do backend)');
  }
}

async function enviarTexto() {
  const telefone = document.getElementById('telefone').value.trim();
  const texto = document.getElementById('texto').value.trim();
  if (!telefone || !texto) { alert('Preencha telefone e mensagem.'); return; }

  adicionarMensagem('inquilino', texto);
  document.getElementById('texto').value = '';

  try {
    await postMensagem({ telefone, texto });
  } catch (e) {
    adicionarMensagem('erro', 'Erro de rede: ' + e);
  }
}

async function enviarComprovante() {
  const telefone = document.getElementById('telefone').value.trim();
  const arquivoInput = document.getElementById('arquivo');
  const arquivo = arquivoInput.files[0];
  if (!telefone || !arquivo) { alert('Preencha telefone e escolha um arquivo.'); return; }

  adicionarMensagem('inquilino', '[comprovante: ' + arquivo.name + ']');

  try {
    const base64 = await arquivoParaBase64(arquivo);
    await postMensagem({ telefone, imagem_base64: base64, media_type: arquivo.type || 'image/jpeg' });
    arquivoInput.value = '';
  } catch (e) {
    adicionarMensagem('erro', 'Erro de rede: ' + e);
  }
}

function arquivoParaBase64(arquivo) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // reader.result é "data:<mime>;base64,<dados>" — só queremos a parte depois da vírgula.
      const base64 = reader.result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(arquivo);
  });
}

async function enviarClique() {
  const telefone = document.getElementById('telefone').value.trim() || '+5500000000000';
  const acao = document.getElementById('acaoBotao').value;
  const contractId = document.getElementById('contractIdBotao').value.trim();
  const chargeIds = document.getElementById('chargeIdsBotao').value.trim();
  if (!contractId || !chargeIds) { alert('Preencha contract_id e charge_id(s).'); return; }

  const buttonId = acao + '|' + contractId + '|' + chargeIds;
  adicionarMensagem('inquilino', '[Fernanda clicou: ' + acao + ']');

  try {
    await postMensagem({ telefone, button_id: buttonId });
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
  if (e.key === 'Enter') enviarTexto();
});
</script>
</body>
</html>
"""
