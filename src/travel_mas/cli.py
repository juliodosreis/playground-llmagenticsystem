"""CLI do sistema multiagente: catálogo, cenários, execução e comparação de topologias."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from .agents.mas import TOPOLOGIAS, build_graph
from .domain import FLIGHTS, HOTELS, diff_state
from .evaluation import (
    SpecError,
    combine_specs,
    compare_models,
    comparison_rows,
    format_comparison,
)
from .evaluation.casos import CASOS
from .evaluation.suite import arun_cases, summary
from .evaluation.validation import validar
from .runtime import (
    Context,
    RunResult,
    Workspace,
    format_rows,
    format_trace,
    run_task,
)
from .runtime.faults import DEFEITOS, capabilities
from .runtime.runner import event_loop
from .scenarios import SCENARIOS


def config_of(context: Context) -> dict[str, Any]:
    """Configuração que acompanha os resultados serializados."""
    return asdict(context)


def print_config(context: Context) -> None:
    print(f"CONFIGURAÇÃO  {context.provider}:{context.model} | topologia {context.topologia}")


def print_json(result: RunResult, context: Context) -> None:
    """Imprime a execução em JSON, precedida pela configuração."""
    print("\nJSON")
    execucao = {"config": config_of(context), **result.to_dict()}
    print(json.dumps(execucao, ensure_ascii=False, indent=2))


def print_run(name: str, result: RunResult) -> None:
    """Imprime transferências, ferramentas, banco e mensagem final."""
    print(f"\n{'=' * 78}\nCENÁRIO {name}  ({result.seconds}s)\n{'=' * 78}")
    print(f"PEDIDO\n  {result.prompt}\n")

    if result.error:
        print(f"ERRO\n  {result.error}\n")

    if result.bitacora:
        print("TRANSFERÊNCIAS")
        for evento in result.bitacora:
            print(f"  {evento['de']} → {evento['para']}: {evento['mensagem_tipo']}")
        print()

    print("TRAJETÓRIA (chamadas de ferramenta)")
    print(format_trace(result.trace))

    print("\nESTADO FINAL (tabela bookings)")
    print(format_rows(result.bookings()))

    mudancas = diff_state(result.before, result.after)
    if "flights" in mudancas and mudancas["flights"]["changed"]:
        print("\nASSENTOS CONSUMIDOS")
        for linha in mudancas["flights"]["changed"]:
            antes, depois = linha["antes"]["seats"], linha["depois"]["seats"]
            print(f"  {linha['id']}: {antes} -> {depois} assentos")

    print("\nMENSAGEM FINAL AO USUÁRIO")
    print(f"  {result.final or '(vazia)'}")


def command_demo(args: argparse.Namespace) -> int:
    keys = args.scenarios or list(SCENARIOS)
    desconhecidos = [k for k in keys if k not in SCENARIOS]
    if desconhecidos:
        print(f"cenário inexistente: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    workspace = Workspace()
    agent = build_graph(workspace, args.context)
    print_config(args.context)
    falhou = False
    for key in keys:
        scenario = SCENARIOS[key]
        result = run_task(agent, workspace, scenario.prompt, args.context.recursion_limit)
        print_run(f"{key}: {scenario.name}", result)
        if args.json:
            print_json(result, args.context)
        falhou = falhou or result.error is not None
    return int(falhou)


def command_run(args: argparse.Namespace) -> int:
    workspace = Workspace()
    agent = build_graph(workspace, args.context)
    print_config(args.context)
    result = run_task(agent, workspace, args.prompt, args.context.recursion_limit)
    print_run("livre", result)
    if args.json:
        print_json(result, args.context)
    return int(result.error is not None)


def command_compare(args: argparse.Namespace) -> int:
    keys = args.scenarios or list(SCENARIOS)
    desconhecidos = [k for k in keys if k not in SCENARIOS]
    if desconhecidos:
        print(f"cenário inexistente: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    overrides = {
        key: value
        for key, value in asdict(args.context).items()
        if key not in ("provider", "model", "topologia")
    }
    modelos = args.modelo or [f"{args.context.provider}:{args.context.model}"]
    topologias = args.topologia_comparar or [args.context.topologia]
    try:
        specs = combine_specs(modelos, topologias, **overrides)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2

    if len(specs) < 2:
        mensagem = "a comparação pede duas configurações: repita --modelo ou --topologia"
        print(mensagem, file=sys.stderr)
        return 2

    rotulos = [spec.label for spec in specs]

    comparison = compare_models(specs, keys)
    print(f"\n{'=' * 78}\nCOMPARAÇÃO: {' | '.join(rotulos)}\n{'=' * 78}")
    print(format_comparison(comparison))

    if args.json:
        print("\nJSON")
        print(json.dumps(comparison_rows(comparison), ensure_ascii=False, indent=2))
    return 0


def command_scenarios(_: argparse.Namespace) -> int:
    for scenario in SCENARIOS.values():
        print(f"{scenario.key}. {scenario.name}\n   {scenario.prompt}\n")
    return 0


def command_catalog(_: argparse.Namespace) -> int:
    print("VOOS")
    print(format_rows([flight._asdict() for flight in FLIGHTS]))
    print("\nHOTÉIS")
    print(format_rows([hotel._asdict() for hotel in HOTELS]))
    return 0


def command_capabilities(_):
    print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
    return 0


def command_validate(args):
    print_config(args.context)

    def progresso(fase, run):
        print(
            f"{fase} {run.config['topologia']} {','.join(run.config['defeitos']) or 'normal'} "
            f"{run.caso}/{run.repeticao}: {run.avaliacao.status}",
            flush=True,
        )

    resultado = event_loop().run_until_complete(
        validar(
            args.context,
            args.output,
            args.k,
            args.jobs,
            on_result=progresso,
        )
    )
    print(f"Relatório: {Path(args.output) / 'README.md'}")
    return int(
        any(r["pass^k"] == 0 for r in resultado["referencia"]["casos"])
        or any(not r["detectado"] or not r["controle_passou"] for r in resultado["defeitos"])
    )


def command_cases(args):
    keys = args.ids or list(CASOS)
    desconhecidos = set(keys) - CASOS.keys()
    if desconhecidos:
        raise ValueError(f"casos desconhecidos: {sorted(desconhecidos)}")
    if args.listar:
        for key in keys:
            caso = CASOS[key]
            print(f"{key}: {caso.nome}" + (f" — {caso.pendente}" if caso.pendente else ""))
        return 0
    print_config(args.context)

    def progresso(run):
        falhas = sorted(
            {c.regra_origem.rsplit(".", 1)[-1] for c in run.avaliacao.checks if c.status == "fail"}
        )
        print(
            f"{run.caso} [{run.repeticao}/{args.k}] {run.avaliacao.status} " + ", ".join(falhas),
            flush=True,
        )

    runs = event_loop().run_until_complete(
        arun_cases(
            [CASOS[key] for key in keys],
            args.context,
            args.k,
            args.jobs,
            on_result=progresso,
        )
    )
    resumo = summary(runs)
    rows = [
        {
            "caso": r["caso"],
            "pass": f"{r['pass']}/{r['k']}",
            "pass^k": r["pass^k"],
            "regras": ", ".join(r["regras_falhas"]),
        }
        for r in resumo["casos"]
    ]
    print(format_rows(rows))
    print(
        f"pass^k agregado: {resumo['pass^k']}; "
        f"não avaliáveis/não ativados: {resumo['nao_avaliaveis']}"
    )
    payload = {"resumo": resumo, "execucoes": [r.to_dict() for r in runs]}
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print(f"Relatório: {path}")
    if args.json:
        print("\nJSON")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return int(any(r.avaliacao.status != "pass" for r in runs))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="travel_mas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--provider", help="ollama, google ou gemini")
    parser.add_argument("--model", help="identificador do modelo; vazio usa o padrão do provedor")
    parser.add_argument("--topologia", choices=list(TOPOLOGIAS), help="coordenação do MAS")
    parser.add_argument("--max-rodadas", type=int, help="máximo de ativações de agentes")
    parser.add_argument(
        "--defeito", action="append", choices=DEFEITOS, help="defeito semeado; repita para combinar"
    )
    parser.add_argument("--max-steps", type=int, help="chamadas ao modelo antes de encerrar")
    parser.add_argument("--json", action="store_true", help="imprime a execução em JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="roda os cenários do playground")
    demo.add_argument("scenarios", nargs="*", help="números dos cenários; vazio roda todos")
    demo.set_defaults(func=command_demo)

    livre = sub.add_parser("run", help="roda um pedido livre")
    livre.add_argument("prompt")
    livre.set_defaults(func=command_run)

    comparar = sub.add_parser(
        "comparar",
        help="compara modelos e topologias",
    )
    comparar.add_argument(
        "--modelo",
        action="append",
        metavar="PROVEDOR[:MODELO]",
        help="modelo a comparar; repita a opção uma vez por modelo. Vazio usa o modelo global",
    )
    comparar.add_argument(
        "--topologia",
        dest="topologia_comparar",
        action="append",
        choices=list(TOPOLOGIAS),
        help="topologia a comparar; repita para comparar workflow e supervisor",
    )
    comparar.add_argument("scenarios", nargs="*", help="números dos cenários; vazio roda todos")
    comparar.set_defaults(func=command_compare)

    listar = sub.add_parser("cenarios", help="lista os cenários")
    listar.set_defaults(func=command_scenarios)

    catalogo = sub.add_parser("catalogo", help="imprime o catálogo do ambiente")
    catalogo.set_defaults(func=command_catalog)

    casos = sub.add_parser("casos", help="avalia casos e calcula pass^k")
    casos.add_argument("ids", nargs="*")
    casos.add_argument("--k", type=int, default=3)
    casos.add_argument("--jobs", type=int, default=1, help="execuções concorrentes")
    casos.add_argument("--listar", action="store_true", help="lista sem carregar um LLM")
    casos.add_argument("--output", help="arquivo JSON com avaliações e traças completas")
    casos.add_argument("--defeito", dest="defeitos_caso", action="append", choices=DEFEITOS)
    casos.set_defaults(func=command_cases)
    capacidades = sub.add_parser("capabilities", help="capacidades do adaptador em JSON")
    capacidades.set_defaults(func=command_capabilities)
    validar_parser = sub.add_parser("validar", help="matriz de referência, defeitos e controles")
    validar_parser.add_argument("--k", type=int, default=3)
    validar_parser.add_argument("--jobs", type=int, default=3)
    validar_parser.add_argument("--output", default="reports/mas-validation")
    validar_parser.set_defaults(func=command_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv())
    args = build_parser().parse_args(argv)

    overrides = {
        key: value
        for key, value in (
            ("provider", args.provider),
            ("model", args.model),
            ("topologia", args.topologia),
            ("max_rodadas", args.max_rodadas),
            ("max_steps", args.max_steps),
            (
                "defeitos",
                tuple((args.defeito or []) + (getattr(args, "defeitos_caso", None) or []))
                if (getattr(args, "defeitos_caso", None) or args.defeito)
                else None,
            ),
        )
        if value is not None
    }
    try:
        args.context = Context(**overrides)
        return args.func(args)
    except RuntimeError as exc:  # chave de API ausente: imprime a mensagem, sem traceback
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:  # configuração inválida vinda do ambiente
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
