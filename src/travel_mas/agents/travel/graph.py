"""Montagem do agente: resolve workspace, modelo e ferramentas, e escolhe a estratégia do grafo.

`Context.strategy` nomeia a estratégia, e `graphs.STRATEGIES` traz o montador de cada uma:

- `react`: o laço de ferramentas, em que o modelo decide a próxima chamada a cada turno;
- `plan-execute`: um plano escrito antes da primeira chamada, executado passo a passo, com um
  desvio ao replanejador quando uma busca volta vazia ou uma ferramenta devolve erro.

As duas estratégias recebem as mesmas ferramentas, declaradas em `tools.py`, e escrevem a mensagem
final em `messages`. O harness roda qualquer uma das duas sem distinção.

`Context.tool_source` nomeia a fonte das ferramentas: `local` ou `mcp`. As duas fontes publicam os
mesmos nomes e schemas, e as estratégias não as distinguem.

`Context.procedure` nomeia a origem do procedimento: `prompt`, com o fluxo de reserva no prompt de
sistema, ou `skills`, com o fluxo lido pela ferramenta `read_skill`. No laço ReAct, `read_skill` é
uma ferramenta como as outras. No Plan-and-Execute, a leitura antecede o planejador.

Os nós do modelo são assíncronos, então o grafo se invoca por `ainvoke`. Uma ferramenta sincrônica
roda nesse grafo sem alteração, e a ferramenta assíncrona do cliente MCP roda pelo mesmo caminho.
"""

from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from ...runtime import PROCEDURES, Context, Workspace, load_chat_model
from ...tools import TOOL_SOURCES
from .graphs import STRATEGIES, StrategyBuilder
from .tools import abuild_agent_tools, build_agent_tools


def resolve_strategy(context: Context) -> StrategyBuilder:
    """O montador da estratégia do contexto, depois de validar estratégia, fonte e procedimento.

    Um nome fora de `STRATEGIES`, de `TOOL_SOURCES` ou de `PROCEDURES` levanta `ValueError`.
    """
    montador = STRATEGIES.get(context.strategy)
    if montador is None:
        conhecidas = ", ".join(STRATEGIES)
        raise ValueError(f"estratégia desconhecida: {context.strategy!r}. Use {conhecidas}.")
    if context.tool_source not in TOOL_SOURCES:
        conhecidas = ", ".join(TOOL_SOURCES)
        raise ValueError(
            f"fonte de ferramentas desconhecida: {context.tool_source!r}. Use {conhecidas}."
        )
    if context.procedure not in PROCEDURES:
        conhecidos = ", ".join(PROCEDURES)
        raise ValueError(f"procedimento desconhecido: {context.procedure!r}. Use {conhecidos}.")
    return montador


def build_graph(
    workspace: Workspace | None = None,
    context: Context | None = None,
    model: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Compila o agente sobre um workspace, com a estratégia de `context.strategy`.

    O workspace é o banco desta execução. As ferramentas fecham sobre ele, então trocar o banco
    entre execuções é chamar `Workspace.reset()`, sem reconstruir o grafo. Com a fonte `mcp`, o
    servidor também fica ligado a esse workspace. Uma estratégia, uma fonte ou um procedimento
    desconhecido levanta `ValueError` antes da carga do modelo.

    Sem `tools`, a fonte `mcp` lê o catálogo do servidor em um laço de eventos próprio. Dentro de
    um laço em execução, `build_graph` levanta `RuntimeError`, e o chamador usa `abuild_graph`.
    """
    context = context or Context()
    montador = resolve_strategy(context)

    workspace = workspace if workspace is not None else Workspace()
    model = model if model is not None else load_chat_model(context)
    if tools is None:
        tools = build_agent_tools(workspace, context.tool_source, context.procedure)
    return montador(model, tools, context)


async def abuild_graph(
    workspace: Workspace | None = None,
    context: Context | None = None,
    model: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Variante assíncrona de `build_graph`, que lê o catálogo MCP no laço em execução.

    `Workspace()` abre SQLite, e a carga do modelo cria o cliente HTTP, as duas de forma
    sincrônica. `asyncio.to_thread` roda essas etapas em um thread, fora do laço.
    """
    context = context or Context()
    resolve_strategy(context)
    if workspace is None:
        workspace = await asyncio.to_thread(Workspace)
    if tools is None:
        tools = await abuild_agent_tools(workspace, context.tool_source, context.procedure)
    return await asyncio.to_thread(build_graph, workspace, context, model, tools)


async def make_graph() -> CompiledStateGraph:
    """Grafo para o LangGraph Studio, com a estratégia, a fonte e o procedimento do ambiente.

    O servidor chama esta função a cada execução, e o grafo roda sobre um workspace novo: cada
    execução parte de um banco sem reservas, também dentro da mesma thread. O checkpointer do
    servidor guarda as mensagens da thread, e não o banco.

    O servidor do Studio chama esta função no laço de eventos. `abuild_graph` roda as etapas
    sincrônicas em um thread, e o servidor monta o grafo sem `--allow-blocking`.
    """
    return await abuild_graph()


async def make_plan_execute_graph() -> CompiledStateGraph:
    """Grafo Plan-and-Execute para o LangGraph Studio, montado como `make_graph`."""
    return await abuild_graph(context=Context(strategy="plan-execute"))


async def make_mcp_graph() -> CompiledStateGraph:
    """Grafo com as ferramentas do servidor MCP, montado como `make_graph`."""
    return await abuild_graph(context=Context(tool_source="mcp"))


async def make_skills_graph() -> CompiledStateGraph:
    """Grafo com o procedimento lido das skills, montado como `make_graph`."""
    return await abuild_graph(context=Context(procedure="skills"))
