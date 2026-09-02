import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import charges, contracts, whatsapp

# Sem isto, o root logger nasce em WARNING e os logs estruturados de
# app/tools/whatsapp_client.py (_log_operacao — "operacao=enviar_texto
# telefone=*** simulado=True/False ...") nunca aparecem nos logs do
# processo (Railway, ou o terminal local), mesmo com a mensagem sendo
# processada com sucesso. É esse log que confirma, na homologação (WA-10,
# docs/whatsapp/homologacao-staging.md, seção 8), que o kill switch
# (WHATSAPP_ENVIO_ATIVO) realmente tomou efeito depois de ligado — sem
# ele, só dá pra confirmar de forma indireta (mensagem chegou ou não no
# celular). Mesmo ajuste já usado em app/jobs/cron_cobranca_diaria.py e
# app/jobs/cron_alertas_contratuais.py, faltava só aqui na API.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Projeto Domingos Monteiro — API")

# Em dev: CORS_ALLOW_ORIGINS não precisa estar setada (default abaixo).
# Em produção: definir como lista separada por vírgula, ex:
#   CORS_ALLOW_ORIGINS=https://app.domingosmonteiro.com.br
_cors_origins = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:8080").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["POST"],
    allow_headers=["*"],
)

app.include_router(contracts.router)
app.include_router(charges.router)
# Webhook do WhatsApp: chamado pela Meta (server-to-server), não por
# navegador — não passa pelo CORSMiddleware acima, que só afeta chamadas
# feitas por browser.
app.include_router(whatsapp.router)

# Chat simulado (dev_chat): ferramenta de teste que expõe uma página HTML +
# endpoint pra simular mensagens do WhatsApp sem a API real da Meta. Nunca
# incluir em produção — qualquer pessoa com a URL poderia mandar mensagem
# "como se fosse" qualquer telefone cadastrado em contracts.
if os.environ.get("ENVIRONMENT", "development") != "production":
    from app.api.routers import dev_chat

    app.include_router(dev_chat.router)