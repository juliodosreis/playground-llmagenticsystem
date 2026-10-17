"""Compara oráculos em traças salvas, sem executar agentes nem alterar as evidências."""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from travel_mas.evaluation.casos import CASOS
from travel_mas.evaluation.checks import avaliar
from travel_mas.runtime import RunResult, ToolCall


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diretorios", type=Path, nargs="+")
    parser.add_argument("--baseline", default="b78b999")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("o arquivo de saída já existe")
    base = subprocess.check_output(["git", "rev-parse", args.baseline], text=True).strip()
    fonte = subprocess.check_output(
        ["git", "show", f"{base}:src/travel_mas/evaluation/checks.py"], text=True
    )
    anterior = ModuleType("travel_mas.evaluation._checks_baseline")
    anterior.__package__ = "travel_mas.evaluation"
    sys.modules[anterior.__name__] = anterior
    exec(compile(fonte, f"{base}:checks.py", "exec"), anterior.__dict__)
    arquivos = sorted(Path("src/travel_mas").rglob("*.py"))
    arquivos += [Path("spec/mas.yaml")]
    payload = {
        "tipo": "reavaliacao_offline",
        "escopo": "Oráculos sobre dados capturados; operações de domínio e grafo não executados.",
        "data_utc": datetime.now(UTC).isoformat(),
        "baseline_commit": base,
        "novas_execucoes_de_agentes": 0,
        "chamadas_ao_provedor": 0,
        "arquivos": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in arquivos},
        "diretorios": [],
    }
    for root in args.diretorios:
        antes, depois = Counter(), Counter()
        alteracoes, ignoradas = [], 0
        hashes = {}
        for path in sorted(root.glob("*.json")):
            conteudo = path.read_bytes()
            raw = json.loads(conteudo)
            if "avaliacao" not in raw:
                continue
            hashes[path.name] = hashlib.sha256(conteudo).hexdigest()
            if raw.get("resultado") is None:
                ignoradas += 1
                continue
            dados = {
                k: v for k, v in raw["resultado"].items() if k in RunResult.__dataclass_fields__
            }
            dados["trace"] = [ToolCall(**c) for c in dados["trace"]]
            resultado = RunResult(**dados)
            antiga = anterior.avaliar(resultado, CASOS[raw["caso"]])
            nova = avaliar(resultado, CASOS[raw["caso"]])
            antes[antiga.status] += 1
            depois[nova.status] += 1
            por_nome = {c.expectativa: c for c in antiga.checks}
            changes = [
                {"expectativa": c.expectativa, "regra_origem": c.regra_origem,
                 "antes": por_nome[c.expectativa].status, "depois": c.status,
                 "detalhe": c.detalhe}
                for c in nova.checks
                if c.expectativa in por_nome and por_nome[c.expectativa].status != c.status
            ]
            if changes or antiga.status != nova.status:
                alteracoes.append({
                    "traca": path.name, "antes": antiga.status, "depois": nova.status,
                    "checks": changes,
                })
            assert path.read_bytes() == conteudo, f"evidência alterada: {path}"
        payload["diretorios"].append({
            "diretorio": str(root), "antes": dict(antes), "depois": dict(depois),
            "sem_resultado": ignoradas, "alteracoes": alteracoes, "tracas_sha256": hashes,
        })
        print(f"{root}: {dict(antes)} -> {dict(depois)}; {len(alteracoes)} traças com mudanças.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as destino:
        destino.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
