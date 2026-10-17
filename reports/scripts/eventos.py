"""Uso: uv run python reports/scripts/eventos.py reports/<dir>/<traça>.json

Imprime a sequência de eventos (handoffs, ferramentas, saídas dos agentes) e a resposta final.
"""

import json
import sys


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)


def linha(e: dict) -> tuple:
    tipo = e["tipo"]
    if tipo == "handoff":
        conteudo = e.get("recebido") or e.get("conteudo")
        perdida = "" if e.get("entregue", True) else "PERDIDA"
        return (
            e["seq"], "HANDOFF", e["de"], "->", e["para"], e["mensagem_tipo"],
            _json(conteudo)[:300], perdida,
        )
    if tipo == "tool_call":
        return (
            e["seq"], "CALL", e["agente"], e["ferramenta"], e["chamada_id"],
            _json(e["argumentos"]),
        )
    if tipo == "tool_result":
        return e["seq"], "RESULT", e["ferramenta"], e["chamada_id"], e["resultado"][:200]
    if tipo == "agent_end":
        return e["seq"], "END", e["agente"], _json(e["saida"])[:400]
    return e["seq"], tipo.upper(), {k: v for k, v in e.items() if k not in ("seq", "tipo")}


def main(argv: list[str]) -> int:
    with open(argv[0]) as f:
        resultado = json.load(f)["resultado"]
    for evento in resultado["eventos"]:
        print(*linha(evento))
    print("FINAL:", resultado.get("final"))
    print("ERROR:", resultado.get("error"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
