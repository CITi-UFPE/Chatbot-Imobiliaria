"""Script standalone pra testar SÓ a classificação de intenção do orquestrador
(app/orchestrator/classificador.py) — sem tocar em banco, sem precisar de um
contrato de teste, sem rodar nenhum agente de verdade. Só precisa de
ANTHROPIC_API_KEY no .env. Útil pra calibrar o system prompt do classificador
rapidinho, sem passar pelo fluxo inteiro (webhook/chat simulado/banco).

Uso:
    python -m app.orchestrator.testar_classificacao "quero saber quando vence meu aluguel"

Sem argumento, abre modo interativo (digita várias mensagens seguidas).
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from app.orchestrator.classificador import classificar_intencao  # noqa: E402


def _classificar_e_mostrar(texto: str) -> None:
    resultado = classificar_intencao(texto)
    print(f"  agente:   {resultado.agente}")
    print(f"  motivo:   {resultado.motivo}")
    print(f"  urgencia: {resultado.urgencia}")


def main() -> int:
    if len(sys.argv) > 1:
        _classificar_e_mostrar(" ".join(sys.argv[1:]))
        return 0

    print("Modo interativo — digite uma mensagem e Enter (linha vazia ou Ctrl+C pra sair).")
    while True:
        try:
            texto = input("\nmensagem> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not texto:
            break
        _classificar_e_mostrar(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
