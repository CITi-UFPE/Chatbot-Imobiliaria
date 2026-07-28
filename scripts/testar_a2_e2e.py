"""Script interativo pra testar o fluxo reativo do A2 (comprovante + clique
de botão da Fernanda) ponta a ponta, contra o backend local já rodando —
sem precisar montar tudo na mão pelo `/dev/chat-simulado/`.

Cobre exatamente os dois primeiros blocos do roteiro de teste manual
(comprovante -> aguardando_confirmacao -> clique "Confirmar" ->
confirmado), automatizando a checagem no Supabase entre cada passo.

Pré-requisitos:
  - Backend rodando local: `uvicorn app.api.main:app --reload --port 8000`
  - .env carregado com SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_JWT_SECRET
  - Um contrato de teste já existente em `contracts`, status='ativo', com
    telefone_whatsapp conhecido
  - Pelo menos 1 charge desse contrato com status 'pendente' ou 'atrasado'
    (criar manualmente no Supabase Table Editor se ainda não tiver)

A "imagem" enviada é um PNG de 1x1 pixel — não é um comprovante de verdade,
então a extração por visão (Claude) provavelmente vai marcar
legivel=false. Isso é um resultado de teste válido: confirma que o fluxo
inteiro roda sem quebrar mesmo com leitura ruim, sem custar uma imagem
real. Pra testar o CASAMENTO de valor de verdade (Caso A/B da lógica de
conciliação), use o upload de arquivo de verdade direto no
/dev/chat-simulado/ com um comprovante real ou uma imagem com o valor
escrito nela.

Uso (a partir da RAIZ do repo — precisa ser -m, não o caminho do arquivo
direto, senão o Python não acha o pacote `app`):
    python -m scripts.testar_a2_e2e
"""

import sys

import requests
from dotenv import load_dotenv

load_dotenv()

from app.orchestrator.agent_auth import obter_client_agente  # noqa: E402
from app.orchestrator.processar_mensagem import _resolver_contract_id  # noqa: E402

BASE_URL = "http://localhost:8000"

_IMAGEM_TESTE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def _titulo(texto: str) -> None:
    print("\n" + "=" * 70)
    print(texto)
    print("=" * 70)


def _listar_charges(client, contract_id: str) -> list[dict]:
    resposta = (
        client.table("charges")
        .select("id, tipo, status, valor_esperado")
        .eq("contract_id", contract_id)
        .execute()
    )
    return resposta.data or []


def main() -> None:
    telefone = input("Telefone do contrato de teste (ex: +5581999999999): ").strip()
    if not telefone:
        print("Telefone obrigatório.")
        sys.exit(1)

    _titulo("1. Resolvendo contract_id pelo telefone")
    contract_id = _resolver_contract_id(telefone)
    if not contract_id:
        print("Nenhum contrato ATIVO encontrado pra esse telefone (confira status='ativo' no Supabase).")
        sys.exit(1)
    print(f"contract_id: {contract_id}")

    client = obter_client_agente(contract_id)

    _titulo("2. Charges em aberto (pendente/atrasado) desse contrato")
    abertas = [c for c in _listar_charges(client, contract_id) if c["status"] in ("pendente", "atrasado")]
    if not abertas:
        print("Nenhuma charge pendente/atrasado encontrada — crie uma no Supabase antes de continuar.")
        sys.exit(1)
    for c in abertas:
        print(f"  - {c['id']}  tipo={c['tipo']}  status={c['status']}  valor={c['valor_esperado']}")

    input("\nPressione Enter para simular o envio de um comprovante (imagem de teste)...")

    _titulo("3. Enviando comprovante simulado")
    resp = requests.post(
        f"{BASE_URL}/dev/chat-simulado/mensagem",
        json={"telefone": telefone, "imagem_base64": _IMAGEM_TESTE_BASE64, "media_type": "image/png"},
        timeout=60,
    )
    resp.raise_for_status()
    print("Resposta do simulado:", resp.json()["resposta"])
    print(
        "\n>>> Confira o terminal do backend — deve ter aparecido um log de "
        "'notificação NÃO enviada para Fernanda' (ou 'pagamento combinado', "
        "se houver 2+ charges em aberto)."
    )

    _titulo("4. Status das charges depois do comprovante")
    depois = _listar_charges(client, contract_id)
    for c in depois:
        print(f"  - {c['id']}  tipo={c['tipo']}  status={c['status']}")

    aguardando = [c for c in depois if c["status"] == "aguardando_confirmacao"]
    if not aguardando:
        print("\nNenhuma charge ficou 'aguardando_confirmacao' — confira os logs do backend pra erro.")
        sys.exit(1)

    if len(aguardando) > 1:
        print(
            f"\n{len(aguardando)} charges ficaram 'aguardando_confirmacao' — parece pagamento "
            "combinado. Este script só automatiza o caso de 1 charge; simule o clique "
            "'combinado_todos' manualmente pelo /dev/chat-simulado/ com os charge_ids: "
            f"{[c['id'] for c in aguardando]}"
        )
        return

    charge = aguardando[0]
    input(f"\nPressione Enter para simular a Fernanda clicando 'Confirmar' na charge {charge['id']}...")

    _titulo("5. Simulando clique de botão (Confirmar)")
    button_id = f"confirmar|{contract_id}|{charge['id']}"
    resp = requests.post(
        f"{BASE_URL}/dev/chat-simulado/mensagem",
        json={"telefone": "+5500000000000", "button_id": button_id},
        timeout=30,
    )
    resp.raise_for_status()
    print("Resposta do simulado:", resp.json()["resposta"])

    _titulo("6. Status final da charge")
    final = client.table("charges").select("status").eq("id", charge["id"]).single().execute().data
    print(f"status final: {final['status']}  (esperado: 'confirmado')")

    if final["status"] == "confirmado":
        print("\nFluxo completo do A2 (comprovante -> confirmação) funcionou de ponta a ponta.")
    else:
        print("\nAlgo não bateu — confira os logs do backend.")


if __name__ == "__main__":
    main()
