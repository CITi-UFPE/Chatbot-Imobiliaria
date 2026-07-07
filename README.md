# Projeto Domingos Monteiro

Sistema multi-agentes via WhatsApp para automação de atendimento, cobrança e gestão contratual de 12 imóveis residenciais, desenvolvido pelo CITi.

## Stack

- **Backend:** Python, FastAPI
- **IA:** Anthropic SDK (Claude Sonnet 4.6)
- **Banco de dados:** Supabase (PostgreSQL + Storage com RLS)
- **Deploy:** Railway
- **HTTP client:** httpx
- **Frontend de gestão:** Lovable

## Arquitetura

Orquestrador determinístico classifica a intenção de cada mensagem recebida via WhatsApp Business API e roteia para um dos 5 agentes especializados:

| Agente | Função |
|---|---|
| A1 | Atendimento ao Inquilino |
| A2 | Cobrança e Inadimplência |
| A3 | Manutenção |
| A4 | Gestão Contratual |
| A5 | Escalonamento Humano |

Detalhes completos de cada agente em `docs/specs/`.

## Estrutura do repositório

```
app/
├── agents/              # Lógica e system prompts de cada agente
│   ├── a1_atendimento/
│   ├── a2_cobranca/
│   ├── a3_manutencao/
│   ├── a4_gestao_contratual/
│   └── a5_escalonamento/
├── orchestrator/        # Classificação de intenção e roteamento
├── tools/               # Tools chamadas pelos agentes (buscar_dados_inquilino, etc)
├── api/                 # Rotas FastAPI, webhook do WhatsApp
├── models/              # Modelos Pydantic / ORM
└── jobs/                # Jobs agendados (arq) — cobrança proativa, reajuste

docs/
├── specs/               # Specs dos 5 agentes, fluxos, documento de validação do cliente
└── schemas/             # Schema do banco (contracts, charges, escalations, etc)

tests/                   # Testes unitários e evals dos agentes
```

## Setup local

```bash
cp .env.example .env
# preencher as variáveis de ambiente
pip install -r requirements.txt --break-system-packages
uvicorn app.api.main:app --reload
```

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
