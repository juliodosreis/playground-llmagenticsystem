"""Harness de execução: roda o agente sobre um ambiente limpo e captura o que ele deixou.

`arun_task` devolve três registros de uma execução: o par de snapshots do banco antes e depois, o
trace de chamadas de ferramenta e a mensagem final ao usuário. Os demais campos do estado final do
grafo, como as bandejas e o relatório tipado, ficam em `RunResult.values`.

Uma exceção do agente preenche o campo `error` do resultado em vez de propagar, então uma sequência
de cenários continua depois de uma falha.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from ..domain import Snapshot
from .faults import MessageFault, ToolFault
from .messages import last_text
from .workspace import ToolCall, Workspace


class AgentLike(Protocol):
    """Interface que o harness exige do agente."""

    async def ainvoke(self, payload: dict, config: dict | None = None) -> dict: ...


@dataclass
class RunResult:
    """Tudo o que uma execução deixa para trás."""

    prompt: str
    before: Snapshot
    after: Snapshot
    trace: list[ToolCall]
    final: str
    messages: Sequence[BaseMessage] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    """Campos do estado final além de `messages`, com os nomes que o grafo declara."""
    error: str | None = None
    seconds: float = 0.0
    eventos: list[dict[str, Any]] = field(default_factory=list)
    bitacora: list[dict[str, Any]] = field(default_factory=list)
    injecoes_esperadas: list[str] = field(default_factory=list)

    def tool_names(self) -> list[str]:
        return [call.name for call in self.trace]

    def bookings(self) -> list[dict[str, Any]]:
        return self.after["bookings"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "before": self.before,
            "after": self.after,
            "trace": [
                {"name": c.name, "args": dict(c.args), "result": c.result} for c in self.trace
            ],
            "final": self.final,
            "values": self.values,
            "error": self.error,
            "seconds": self.seconds,
            "eventos": self.eventos,
            "bitacora": self.bitacora,
            "injecoes_esperadas": self.injecoes_esperadas,
        }


async def arun_task(
    agent: AgentLike,
    workspace: Workspace,
    prompt: str,
    recursion_limit: int = 50,
    *,
    estado_inicial: dict | None = None,
    tool_faults: list[ToolFault] | None = None,
    message_faults: list[MessageFault] | None = None,
) -> RunResult:
    """Executa o agente sobre um banco limpo e devolve o registro da execução."""
    if tool_faults is not None:
        workspace.tool_faults = list(tool_faults)
    if message_faults is not None:
        workspace.message_faults = list(message_faults)
    workspace.reset(estado_inicial)
    before = workspace.snapshot()

    started = time.time()
    error: str | None = None
    final = ""
    messages: Sequence[BaseMessage] = []
    values: dict[str, Any] = {}

    try:
        result = await agent.ainvoke(
            {"pedido_usuario": prompt},
            {"recursion_limit": recursion_limit},
        )
        messages = result.get("messages", [])
        values = {key: value for key, value in result.items() if key != "messages"}
        final = result.get("final") or last_text(messages)
        erros = result.get("relatorio", {}).get("erros", [])
        if result.get("motivo_terminacao") == "error":
            error = "; ".join(erros) or "erro de agente"
    except Exception as exc:  # um crash é um resultado da execução, registrado como tal
        error = f"{type(exc).__name__}: {exc}"
        workspace.emit("error", erro=error)
        final = f"Execução interrompida: {error}"
        workspace.emit("termination", agente="harness", motivo="error", erro=error)

    return RunResult(
        prompt=prompt,
        before=before,
        after=workspace.snapshot(),
        trace=copy.copy(workspace.trace),
        final=final,
        messages=messages,
        values=values,
        error=error,
        seconds=round(time.time() - started, 1),
        eventos=copy.deepcopy(workspace.eventos),
        bitacora=copy.deepcopy([e for e in workspace.eventos if e["tipo"] == "handoff"]),
        injecoes_esperadas=[f.id for f in [*workspace.tool_faults, *workspace.message_faults]],
    )


_LOOP: asyncio.AbstractEventLoop | None = None


def event_loop() -> asyncio.AbstractEventLoop:
    """O laço de eventos do processo, criado na primeira chamada e mantido aberto.

    O cliente HTTP de um provedor de modelo é criado sob demanda e fica preso ao laço em que
    nasceu. `asyncio.run` fecha o laço ao terminar, então a segunda execução do processo
    encontraria esse cliente inválido e levantaria `RuntimeError: Event loop is closed`. As
    execuções de uma suíte de cenários compartilham um laço só.
    """
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP


def run_task(
    agent: AgentLike,
    workspace: Workspace,
    prompt: str,
    recursion_limit: int = 50,
    **kwargs,
) -> RunResult:
    """Envoltório sincrônico de `arun_task`, para a CLI.

    Em código que já roda dentro de um laço de eventos, como uma célula de notebook, chame
    `arun_task` com `await`.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return event_loop().run_until_complete(
            arun_task(agent, workspace, prompt, recursion_limit, **kwargs)
        )
    raise RuntimeError(
        "há um laço de eventos em execução neste processo. Use `await arun_task(...)` em vez de "
        "`run_task(...)`."
    )
