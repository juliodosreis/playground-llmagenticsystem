"""Uso: uv run python reports/scripts/resumo.py reports/<dir>/*-*-*.json

Uma linha por traça: status e checks que não passaram.
"""
import json, sys, os
for path in sys.argv[1:]:
    r = json.load(open(path))
    av = r["avaliacao"]
    falhas = [f"{c['expectativa']}[{c['regra_origem'].rsplit('.',1)[-1]}]:{c['detalhe'][:140]}" for c in av["checks"] if c["status"] != "pass"]
    print(f"{os.path.basename(path)}: {av['status']}  " + " | ".join(falhas))
