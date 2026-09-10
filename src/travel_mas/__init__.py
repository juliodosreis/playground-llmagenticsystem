"""Agente de reservas de viagem em LangGraph.

Camadas do pacote:

    domain/     catálogo, banco e regras de reserva, sem LangChain
    runtime/    configuração, modelo, workspace e harness
    tools/      as ferramentas ligadas a um workspace, agrupadas por efeito
    agents/     um pacote por agente: prompt, ferramentas, estado e grafo

Uso:

    from travel_mas import Context, Workspace, build_graph, run_task

    workspace = Workspace()
    agent = build_graph(workspace, Context())
    result = run_task(agent, workspace, "Quero voar de MAD para LIM em 2026-09-12.")
"""

from .agents.travel import TravelState, build_agent_tools, build_graph, make_graph
from .domain import diff_state
from .runtime import Context, RunResult, ToolCall, Workspace, arun_task, run_task
from .tools import Toolbox, build_toolbox

__all__ = [
    "Context",
    "RunResult",
    "ToolCall",
    "Toolbox",
    "TravelState",
    "Workspace",
    "arun_task",
    "build_agent_tools",
    "build_graph",
    "build_toolbox",
    "diff_state",
    "make_graph",
    "run_task",
]
