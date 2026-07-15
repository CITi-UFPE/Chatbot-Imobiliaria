import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import contracts, whatsapp

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
# Webhook do WhatsApp: chamado pela Meta (server-to-server), não por
# navegador — não passa pelo CORSMiddleware acima, que só afeta chamadas
# feitas por browser.
app.include_router(whatsapp.router)
