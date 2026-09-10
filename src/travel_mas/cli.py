"""Entrada de linha de comando: roda cenários e imprime as três evidências da execução.

    python -m travel_mas cenarios              # lista os cenários
    python -m travel_mas demo                  # roda todos
    python -m travel_mas demo 2 4              # roda os cenários 2 e 4
    python -m travel_mas run "texto do pedido" # roda um pedido livre
    python -m travel_mas catalogo              # imprime voos e hotéis do ambiente
    python -m travel_mas comparar \
        --modelo ollama --modelo google        # roda os cenários por dois modelos

Cada execução parte de um banco limpo e imprime a trajetória de chamadas, a tabela `bookings`
resultante, os assentos consumidos e a mensagem final.
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import find_dotenv, load_dotenv

from .agents.travel import build_graph
from .domain import FLIGHTS, HOTELS, diff_state
from .evaluation import SpecError, compare_models, comparison_rows, format_comparison, parse_spec
from .runtime import Context, RunResult, Workspace, format_rows, format_trace, run_task
from .scenarios import SCENARIOS


def print_run(name: str, result: RunResult) -> None:
    """Imprime trajetória, estado do banco e mensagem final, nessa ordem."""
    print(f"\n{'=' * 78}\nCENÁRIO {name}  ({result.seconds}s)\n{'=' * 78}")
    print(f"PEDIDO\n  {result.prompt}\n")

    if result.error:
        print(f"ERRO\n  {result.error}\n")

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
    for key in keys:
        scenario = SCENARIOS[key]
        result = run_task(agent, workspace, scenario.prompt, args.context.recursion_limit)
        print_run(f"{key}: {scenario.name}", result)
        if args.json:
            print("\nJSON")
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def command_run(args: argparse.Namespace) -> int:
    workspace = Workspace()
    agent = build_graph(workspace, args.context)
    result = run_task(agent, workspace, args.prompt, args.context.recursion_limit)
    print_run("livre", result)
    if args.json:
        print("\nJSON")
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    keys = args.scenarios or list(SCENARIOS)
    desconhecidos = [k for k in keys if k not in SCENARIOS]
    if desconhecidos:
        print(f"cenário inexistente: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    overrides = {"max_steps": args.max_steps} if args.max_steps is not None else {}
    try:
        specs = [parse_spec(texto, **overrides) for texto in args.modelo]
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2

    rotulos = [spec.label for spec in specs]
    if len(set(rotulos)) < len(rotulos):
        print(f"modelos repetidos na comparação: {', '.join(rotulos)}", file=sys.stderr)
        return 2

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="travel_mas", description=__doc__)
    parser.add_argument("--provider", help="ollama, google ou gemini")
    parser.add_argument("--model", help="identificador do modelo; vazio usa o padrão do provedor")
    parser.add_argument("--max-steps", type=int, help="chamadas ao modelo antes de encerrar")
    parser.add_argument("--json", action="store_true", help="imprime a execução em JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="roda os cenários do playground")
    demo.add_argument("scenarios", nargs="*", help="números dos cenários; vazio roda todos")
    demo.set_defaults(func=command_demo)

    livre = sub.add_parser("run", help="roda um pedido livre")
    livre.add_argument("prompt")
    livre.set_defaults(func=command_run)

    comparar = sub.add_parser("comparar", help="roda os cenários por vários modelos")
    comparar.add_argument(
        "--modelo",
        action="append",
        required=True,
        metavar="PROVEDOR[:MODELO]",
        help="modelo a comparar; repita a opção uma vez por modelo",
    )
    comparar.add_argument("scenarios", nargs="*", help="números dos cenários; vazio roda todos")
    comparar.set_defaults(func=command_compare)

    listar = sub.add_parser("cenarios", help="lista os cenários")
    listar.set_defaults(func=command_scenarios)

    catalogo = sub.add_parser("catalogo", help="imprime o catálogo do ambiente")
    catalogo.set_defaults(func=command_catalog)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv())
    args = build_parser().parse_args(argv)

    overrides = {
        key: value
        for key, value in (
            ("provider", args.provider),
            ("model", args.model),
            ("max_steps", args.max_steps),
        )
        if value is not None
    }
    args.context = Context(**overrides)

    try:
        return args.func(args)
    except RuntimeError as exc:  # chave de API ausente: imprime a mensagem, sem traceback
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
