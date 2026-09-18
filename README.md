# Projeto Domingos Monteiro

Sistema multi-agentes via WhatsApp para automação de atendimento, cobrança, manutenção e gestão contratual da carteira de imóveis residenciais da Domingos Monteiro, desenvolvido pelo CITi.

Já em produção: atendimento contratual, cobrança automática (aluguel/água), manutenção com classificação de urgência, escalonamento com resposta bidirecional equipe ↔ inquilino, e gestão de renovação/reajuste contratual — tudo pelo mesmo número de WhatsApp, sem app novo pra ninguém instalar.

## Stack

- **Backend:** Python, FastAPI
- **IA:** Anthropic SDK (Claude Sonnet 5)
- **Transporte:** WhatsApp Cloud API (Meta)
- **Banco de dados:** Supabase (PostgreSQL + RLS, sem acesso direto de service_role pelos agentes — ver `docs/schemas/002_auth_rbac_rls.sql`)
- **Deploy:** Railway (backend) + Supabase (banco) + Meta Business Manager (WhatsApp)
- **Frontend de gestão:** React + TanStack Start + Tailwind, construído com Lovable

## Arquitetura

Um webhook recebe a mensagem do WhatsApp, um orquestrador determinístico classifica a intenção e roteia para um dos 5 agentes especializados — cada um com seu próprio system prompt, tools e (quando precisa) máquina de estados:

| Agente | Função |
|---|---|
| A1 | Atendimento ao Inquilino — perguntas sobre o próprio contrato (valor, vencimento, garantia, cláusulas, status de pagamento) |
| A2 | Cobrança — lembretes automáticos de vencimento/atraso, conferência de comprovante, negociação |
| A3 | Manutenção — classifica categoria/urgência do relato e abre chamado com protocolo |
| A4 | Gestão Contratual — alertas de renovação (D-60) e cálculo de reajuste (D-30) |
| A5 | Escalonamento Humano — casos que exigem decisão de gente (jurídico, emergência, desconto, fiador) — inclusive a resposta da equipe voltando pro inquilino pelo reply nativo do WhatsApp |

Nenhum agente recebe `contract_id` como parâmetro livre: o JWT assinado por conversa já escopa qual contrato aquele agente pode enxergar, então um agente nunca consegue puxar dado de um contrato que não é o da conversa atual. Detalhes de cada agente em `docs/specs/`.

## Estrutura do repositório

```
app/
├── agents/              # System prompt + lógica de cada agente
│   ├── a1_atendimento/
│   ├── a2_cobranca/
│   ├── a3_manutencao/
│   ├── a4_gestao_contratual/
│   └── a5_escalonamento/
├── orchestrator/        # Classificação de intenção, roteamento, auth do agente (JWT)
├── tools/               # Tools chamadas pelos agentes (whatsapp_client, extrações, etc)
├── api/                 # Rotas FastAPI — webhook do WhatsApp, endpoints do painel
├── models/              # Modelos Pydantic
└── jobs/                # Crons — cobrança diária (D-5/D0/D+5/D+10/D+15), alertas contratuais

frontend/               # Painel de gestão (contratos, cobranças, água, manutenção, renovações)

docs/
├── specs/      # Spec de cada agente e do fluxo de extração de contrato
├── schemas/    # Migrations do banco, numeradas e aplicadas em ordem no Supabase
└── whatsapp/   # Catálogo de templates aprovados pela Meta + roteiro de homologação

scripts/        # Seeds e testes manuais (homologação, cron com data simulada, etc)
tests/          # Suíte unitária (mock de Claude/Supabase) + tests/integration/ (Supabase de teste real)
```

## Setup local

Backend:

```bash
cp .env.example .env
# preencher as variáveis de ambiente (Supabase, Anthropic, WhatsApp — ver comentários do próprio .env.example)
pip install -r requirements.txt --break-system-packages
uvicorn app.api.main:app --reload
```

Com `ENVIRONMENT` diferente de `production`, fica disponível `/dev/chat-simulado/` — simula o fluxo completo (webhook → orquestrador → agente → banco → resposta) sem depender de mensagem real do WhatsApp.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Testes

```bash
pytest tests -m "not integration" -q   # suíte unitária — sem credencial nenhuma, roda sempre
pytest -m integration -q               # Supabase de teste real — precisa de .env.test (ver tests/integration/README.md)
```

A suíte de integração nunca deve apontar para o Supabase de produção — ela cria e apaga contratos fictícios e muta estado (finalização automática, negociação).

## Deploy

- **Banco:** cada migration em `docs/schemas/` é aplicada em ordem, direto no SQL Editor do projeto Supabase (produção e/ou de teste, nunca cruzando os dois).
- **Backend:** Railway, deploy automático a partir de `develop`/`main` conforme o ambiente.
- **WhatsApp:** número e templates configurados no Meta Business Manager — catálogo completo e status de cada template em `docs/whatsapp/templates-meta.md`. `WHATSAPP_ENVIO_ATIVO` é o kill switch: desligado por padrão, precisa ser ligado explicitamente pra qualquer envio real sair (ver `docs/whatsapp/homologacao-staging.md`).

## Convenção de commits

Seguimos [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: adiciona tool de verificação de status de pagamento`
- `fix: corrige cálculo de reajuste do contrato ARCO`
- `docs: atualiza spec do A5`
- `chore: configura variáveis de ambiente do Railway`

## Time

- Theo Barza — Gerente de Projetos
- Davi Mello — Especialista de Dados
- Julia Andrade — Especialista de Dados
- Daniel Cavalcante — Analista de Dados
