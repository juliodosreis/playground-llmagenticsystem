"""Uso (dentro de reports/): uv run python scripts/ids.py

Conta, por diretório, propostas do Pesquisador com item_id fora do formato FL-n/HT-n (R2).
"""
import json, glob, collections, re
stats = collections.Counter()
exemplos = collections.defaultdict(list)
for path in glob.glob("*/*.json"):
    if path.endswith(("summary.json", "manifest.json")): continue
    r = json.load(open(path))
    res = r.get("resultado")
    if not res: continue
    for e in res["eventos"]:
        if e["tipo"] == "agent_end" and e["agente"] == "pesquisador":
            for p in e["saida"].get("propostas", []):
                ok = bool(re.fullmatch(r"(FL|HT)-\d+", p["item_id"]))
                d = path.split("/")[0]
                stats[(d, ok)] += 1
                if not ok: exemplos[d].append((path.split("/")[1], p["item_id"]))
for k in sorted(stats): print(k, stats[k])
for d, ex in exemplos.items(): print(d, ex)
