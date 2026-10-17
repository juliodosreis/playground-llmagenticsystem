"""Uso: uv run python reports/scripts/ids.py [reports/<dir> ...]

Conta, por diretório, propostas do Pesquisador com item_id fora do formato FL-n/HT-n (R2). Sem
argumentos, lê os subdiretórios do diretório atual, como em `cd reports && python scripts/ids.py`.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

FORMATO = re.compile(r"(FL|HT)-\d+")


def tracas(diretorios: list[Path]):
    for diretorio in diretorios:
        for path in sorted(diretorio.glob("*.json")):
            if path.name not in ("summary.json", "manifest.json"):
                yield diretorio.name, path


def main(argv: list[str]) -> int:
    diretorios = [Path(d) for d in argv] or sorted(p for p in Path().iterdir() if p.is_dir())
    stats = Counter()
    exemplos = defaultdict(list)
    for nome, path in tracas(diretorios):
        with path.open() as f:
            resultado = json.load(f).get("resultado")
        if not resultado:
            continue
        for e in resultado["eventos"]:
            if e["tipo"] != "agent_end" or e["agente"] != "pesquisador":
                continue
            for proposta in e["saida"].get("propostas", []):
                ok = bool(FORMATO.fullmatch(proposta["item_id"]))
                stats[(nome, ok)] += 1
                if not ok:
                    exemplos[nome].append((path.name, proposta["item_id"]))
    for chave in sorted(stats):
        print(chave, stats[chave])
    for nome, lista in exemplos.items():
        print(nome, lista)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
