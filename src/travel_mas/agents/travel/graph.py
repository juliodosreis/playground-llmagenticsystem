"""Montagem do agente: resolve workspace, modelo e ferramentas, e escolhe a estratégia do grafo.

`Context.strategy` nomeia a estratégia, e `graphs.STRATEGIES` traz o montador de cada uma:

- `react`: o laço de ferramentas, em que o modelo decide a próxima chamada a cada turno;
- `plan-execute`: um plano escrito antes da primeira chamada, executado passo a passo, com um
  desvio ao replanejador quando uma busca volta vazia ou uma ferramenta devolve erro.

As duas estratégias recebem as mesmas ferramentas, declaradas em `tools.py`, e escrevem a mensagem
final em `messages`. O harness roda qualquer uma das duas sem distinção.

Os nós do modelo são assíncronos, então o grafo se invoca por `ainvoke`. Uma ferramenta sincrônica
roda nesse grafo sem alteração, e o caminho aceita ferramenta assíncrona, como a de um servidor MCP.
"""

from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from ...runtime import Context, Workspace, load_chat_model
from .graphs import STRATEGIES
from .tools import build_agent_tools


def build_graph(
    workspace: Workspace | None = None,
    context: Context | None = None,
    model: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Compila o agente sobre um workspace, com a estratégia de `context.strategy`.

    O workspace é o banco desta execução. As ferramentas fecham sobre ele, então trocar o banco
    entre execuções é chamar `Workspace.reset()`, sem reconstruir o grafo. Uma estratégia fora de
    `STRATEGIES` levanta `ValueError` antes da carga do modelo.
    """
    context = context or Context()
    montador = STRATEGIES.get(context.strategy)
    if montador is None:
        conhecidas = ", ".join(STRATEGIES)
        raise ValueError(f"estratégia desconhecida: {context.strategy!r}. Use {conhecidas}.")

    workspace = workspace if workspace is not None else Workspace()
    model = model if model is not None else load_chat_model(context)
    tools = tools if tools is not None else build_agent_tools(workspace)
    return montador(model, tools, context)


async def make_graph() -> CompiledStateGraph:
    """Grafo para o LangGraph Studio, sobre um workspace novo, com a estratégia do ambiente.

    O banco fica no processo do servidor: as reservas de uma sessão do Studio continuam visíveis na
    seguinte. `runtime.run_task` parte de um banco limpo a cada execução.

    O servidor do Studio chama esta função no laço de eventos, e `Workspace()` abre SQLite de forma
    sincrônica. `asyncio.to_thread` roda a montagem em um thread, e o servidor monta o grafo sem
    `--allow-blocking`.
    """
    return await asyncio.to_thread(build_graph)


async def make_plan_execute_graph() -> CompiledStateGraph:
    """Grafo Plan-and-Execute para o LangGraph Studio, montado como `make_graph`."""
    return await asyncio.to_thread(build_graph, None, Context(strategy="plan-execute"))
