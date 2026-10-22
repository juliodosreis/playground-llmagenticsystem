"""Uso: uv run python reports/scripts/resumo.py reports/<dir>/*.json

Uma linha por traça: status e checks que não passaram. Arquivos sem `avaliacao`, como
`summary.json` e `manifest.json`, são ignorados.
"""

import json
import sys
from pathlib import Path


def linha(path: Path, avaliacao: dict) -> str:
    falhas = [
        f"{c['expectativa']}[{c['regra_origem'].rsplit('.', 1)[-1]}]:{c['detalhe'][:140]}"
        for c in avaliacao["checks"]
        if c["status"] != "pass"
    ]
    return f"{path.name}: {avaliacao['status']}  " + " | ".join(falhas)


def main(argv: list[str]) -> int:
    for arquivo in argv:
        path = Path(arquivo)
        with path.open() as f:
            dados = json.load(f)
        if "avaliacao" in dados:
            print(linha(path, dados["avaliacao"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
