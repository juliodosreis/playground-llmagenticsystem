"""Tanda de até seis execuções; sem --autorizar-provedor, imprime apenas o plano.

A execução com modelo real exige autorização do usuário. Cada execução contém várias chamadas
ao provedor. O diretório de saída deve ser novo; as evidências anteriores não são sobrescritas.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--casos", nargs="+", required=True)
    parser.add_argument("--topologia", choices=["workflow", "supervisor"], action="append")
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--defeito", choices=[f"D{i}" for i in range(1, 7)])
    parser.add_argument("--autorizar-provedor", action="store_true")
    args = parser.parse_args(argv)
    topologias = list(dict.fromkeys(args.topologia or ["workflow", "supervisor"]))
    casos = list(dict.fromkeys(args.casos))
    total = len(topologias) * len(casos) * args.k
    if args.k < 1 or args.jobs < 1 or total > 6:
        parser.error("k e jobs devem ser positivos; a tanda admite até seis execuções")
    print(f"Plano: {casos}, {topologias}, k={args.k}, total={total}, defeito={args.defeito}.")
    if not args.autorizar_provedor:
        print("Somente planejamento. A execução requer autorização do usuário.")
        return 0
    if args.output.exists():
        parser.error("o diretório de saída já existe; escolha um diretório novo")

    # Configuração de provedor e execução só são carregadas após a confirmação de execução.
    from dotenv import find_dotenv, load_dotenv

    from travel_mas.evaluation.casos import CASOS
    from travel_mas.evaluation.suite import arun_case
    from travel_mas.evaluation.validation import detectou, escrever_relatorio, exigir_ativacao
    from travel_mas.runtime import Context
    from travel_mas.runtime.runner import event_loop

    desconhecidos = set(casos) - CASOS.keys()
    if desconhecidos:
        parser.error(f"casos desconhecidos: {sorted(desconhecidos)}")
    args.output.mkdir(parents=True, exist_ok=False)
    load_dotenv(find_dotenv(usecwd=True))
    base = Context()
    fase = "defeito" if args.defeito else "referencia"
    planos = [
        (
            replace(base, topologia=t, defeitos=(args.defeito,) if args.defeito else ()),
            CASOS[c],
            rep,
        )
        for t in topologias
        for c in casos
        for rep in range(1, args.k + 1)
    ]
    arquivos = sorted(Path("src/travel_mas").rglob("*.py"))
    arquivos += [Path(p) for p in ("spec/mas.yaml", "pyproject.toml", "uv.lock")]
    manifest = {
        "data_utc": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "codigo_modificado": bool(
            subprocess.check_output(
                ["git", "diff", "HEAD", "--", "src", "spec", "pyproject.toml", "uv.lock"]
            )
        ),
        "arquivos": {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in arquivos},
        "planos": [(fase, c.topologia, list(c.defeitos), k.id, r) for c, k, r in planos],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )

    async def executar():
        sem = asyncio.Semaphore(args.jobs)

        async def rodar(config, caso, rep):
            async with sem:
                run = await arun_case(caso, config, rep)
                if args.defeito:
                    exigir_ativacao(run)
                nome = f"{fase}-{config.topologia}-{args.defeito or 'normal'}-{caso.id}-{rep}.json"
                (args.output / nome).write_text(
                    json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n"
                )
                print(f"{nome}: {run.avaliacao.status}", flush=True)
                return fase, run, nome

        return await asyncio.gather(*(rodar(*p) for p in planos))

    resultados = event_loop().run_until_complete(executar())
    escrever_relatorio(resultados, args.output, args.k)
    return int(
        not all(
            detectou(run, args.defeito) if args.defeito else run.avaliacao.status == "pass"
            for _, run, _ in resultados
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
