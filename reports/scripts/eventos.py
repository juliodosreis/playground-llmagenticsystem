"""Uso: uv run python reports/scripts/eventos.py reports/<dir>/<traça>.json

Imprime a sequência de eventos (handoffs, ferramentas, saídas dos agentes) e a resposta final.
"""
import json, sys
r = json.load(open(sys.argv[1]))
res = r["resultado"]
for e in res["eventos"]:
    t = e["tipo"]
    if t == "handoff":
        c = e.get("recebido") or e.get("conteudo")
        print(e["seq"], "HANDOFF", e["de"], "->", e["para"], e["mensagem_tipo"], json.dumps(c, ensure_ascii=False)[:300], "" if e.get("entregue", True) else "PERDIDA")
    elif t == "tool_call":
        print(e["seq"], "CALL", e["agente"], e["ferramenta"], e["chamada_id"], json.dumps(e["argumentos"], ensure_ascii=False))
    elif t == "tool_result":
        print(e["seq"], "RESULT", e["ferramenta"], e["chamada_id"], e["resultado"][:200])
    elif t == "agent_end":
        print(e["seq"], "END", e["agente"], json.dumps(e["saida"], ensure_ascii=False)[:400])
    else:
        print(e["seq"], t.upper(), {k: v for k, v in e.items() if k not in ("seq", "tipo")})
print("FINAL:", res.get("final"))
print("ERROR:", res.get("error"))
