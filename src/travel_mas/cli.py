"""Entrada de linha de comando: roda cenários e imprime as três evidências da execução.

    python -m travel_mas cenarios              # lista os cenários
    python -m travel_mas demo                  # roda todos
    python -m travel_mas demo 2 4              # roda os cenários 2 e 4
    python -m travel_mas run "texto do pedido" # roda um pedido livre
    python -m travel_mas catalogo              # imprime voos e hotéis do ambiente

    python -m travel_mas comparar --modelo ollama --modelo google              # dois modelos
    python -m travel_mas comparar --estrategia react --estrategia plan-execute # duas estratégias
    python -m travel_mas comparar --ferramentas local --ferramentas mcp        # duas fontes
    python -m travel_mas comparar --procedimento prompt --procedimento skills  # dois procedimentos
    python -m travel_mas --strategy plan-execute demo 2  # estratégia Plan-and-Execute
    python -m travel_mas --tools mcp demo 2              # ferramentas pelo servidor MCP
    python -m travel_mas --procedure skills demo 2       # fluxo lido da skill

`demo` e `run` começam pela linha `CONFIGURAÇÃO`, com o modelo, a estratégia, a fonte das
ferramentas e o procedimento. Cada execução parte de um banco limpo e imprime a trajetória de
chamadas, a tabela `bookings` resultante, os assentos consumidos e a mensagem final. Na estratégia
`plan-execute`, a saída traz também o plano executado e as chamadas que o executor recusou. Com
`--json`, o JSON de cada execução leva a configuração no campo `config`.
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import find_dotenv, load_dotenv

from .agents.travel import STRATEGIES, build_graph
from .domain import FLIGHTS, HOTELS, diff_state
from .evaluation import (
    SpecError,
    combine_specs,
    compare_models,
    comparison_rows,
    format_comparison,
)
from .runtime import (
    PROCEDURES,
    Context,
    RunResult,
    Workspace,
    format_rows,
    format_trace,
    run_task,
)
from .scenarios import SCENARIOS
from .tools import TOOL_SOURCES


def config_of(context: Context) -> dict[str, str]:
    """Os cinco campos do contexto que distinguem uma configuração de outra."""
    return {
        "provider": context.provider,
        "model": context.model,
        "strategy": context.strategy,
        "tool_source": context.tool_source,
        "procedure": context.procedure,
    }


def print_config(context: Context) -> None:
    """Imprime a linha de configuração, com os valores das opções globais que montam o agente."""
    print(
        f"CONFIGURAÇÃO  {context.provider}:{context.model} | estratégia {context.strategy} | "
        f"ferramentas {context.tool_source} | procedimento {context.procedure}"
    )


def print_json(result: RunResult, context: Context) -> None:
    """Imprime a execução em JSON, precedida pela configuração."""
    print("\nJSON")
    execucao = {"config": config_of(context), **result.to_dict()}
    print(json.dumps(execucao, ensure_ascii=False, indent=2))


def print_run(name: str, result: RunResult) -> None:
    """Imprime plano, trajetória, estado do banco e mensagem final, nessa ordem.

    O plano e as chamadas recusadas saem apenas quando o estado final do grafo tem os campos
    `plano` e `recusadas`.
    """
    print(f"\n{'=' * 78}\nCENÁRIO {name}  ({result.seconds}s)\n{'=' * 78}")
    print(f"PEDIDO\n  {result.prompt}\n")

    if result.error:
        print(f"ERRO\n  {result.error}\n")

    if "plano" in result.values:
        revisto = " (revisto pelo replanejador)" if result.values.get("replanejado") else ""
        print(f"PLANO{revisto}")
        for indice, passo in enumerate(result.values["plano"], start=1):
            print(f"  {indice}. {passo}")
        print()

    print("TRAJETÓRIA (chamadas de ferramenta)")
    print(format_trace(result.trace))

    if result.values.get("recusadas"):
        print("\nCHAMADAS RECUSADAS (fora da trajetória, sem efeito no banco)")
        for recusa in result.values["recusadas"]:
            print(f"  {recusa}")

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
    for key in keys:
        scenario = SCENARIOS[key]
        result = run_task(agent, workspace, scenario.prompt, args.context.recursion_limit)
        print_run(f"{key}: {scenario.name}", result)
        if args.json:
            print_json(result, args.context)
    return 0


def command_run(args: argparse.Namespace) -> int:
    workspace = Workspace()
    agent = build_graph(workspace, args.context)
    print_config(args.context)
    result = run_task(agent, workspace, args.prompt, args.context.recursion_limit)
    print_run("livre", result)
    if args.json:
        print_json(result, args.context)
    return 0


def command_compare(args: argparse.Namespace) -> int:
    keys = args.scenarios or list(SCENARIOS)
    desconhecidos = [k for k in keys if k not in SCENARIOS]
    if desconhecidos:
        print(f"cenário inexistente: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    overrides = {"max_steps": args.max_steps} if args.max_steps is not None else {}
    modelos = args.modelo or [f"{args.context.provider}:{args.context.model}"]
    estrategias = args.estrategia or [args.context.strategy]
    fontes = args.ferramentas or [args.context.tool_source]
    procedimentos = args.procedimento or [args.context.procedure]
    try:
        specs = combine_specs(modelos, estrategias, fontes, procedimentos, **overrides)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2

    if len(specs) < 2:
        mensagem = (
            "a comparação pede duas configurações: repita --modelo, --estrategia, --ferramentas "
            "ou --procedimento"
        )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="travel_mas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--provider", help="ollama, google ou gemini")
    parser.add_argument("--model", help="identificador do modelo; vazio usa o padrão do provedor")
    parser.add_argument("--strategy", choices=list(STRATEGIES), help="topologia do grafo")
    parser.add_argument(
        "--tools", choices=list(TOOL_SOURCES), help="fonte das ferramentas: local ou mcp"
    )
    parser.add_argument(
        "--procedure",
        choices=list(PROCEDURES),
        help="origem do fluxo de reserva: prompt de sistema ou skills",
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
        help="roda os cenários por modelos, estratégias, fontes de ferramentas e procedimentos",
    )
    comparar.add_argument(
        "--modelo",
        action="append",
        metavar="PROVEDOR[:MODELO]",
        help="modelo a comparar; repita a opção uma vez por modelo. Vazio usa o modelo global",
    )
    comparar.add_argument(
        "--estrategia",
        action="append",
        choices=list(STRATEGIES),
        help="estratégia a comparar; repita a opção uma vez por estratégia. Vazio usa a global",
    )
    comparar.add_argument(
        "--ferramentas",
        action="append",
        choices=list(TOOL_SOURCES),
        help="fonte a comparar; repita a opção uma vez por fonte. Vazio usa a global",
    )
    comparar.add_argument(
        "--procedimento",
        action="append",
        choices=list(PROCEDURES),
        help="procedimento a comparar; repita a opção uma vez por procedimento. Vazio usa o global",
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
            ("strategy", args.strategy),
            ("tool_source", args.tools),
            ("procedure", args.procedure),
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
    except ValueError as exc:  # estratégia, fonte ou procedimento desconhecido vindo do ambiente
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
