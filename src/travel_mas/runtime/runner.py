"""Harness de execução: roda o agente sobre um ambiente limpo e captura o que ele deixou.

`arun_task` devolve três registros de uma execução: o par de snapshots do banco antes e depois, o
trace de chamadas de ferramenta e a mensagem final ao usuário.

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
    error: str | None = None
    seconds: float = 0.0

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
            "error": self.error,
            "seconds": self.seconds,
        }


async def arun_task(
    agent: AgentLike,
    workspace: Workspace,
    prompt: str,
    recursion_limit: int = 50,
) -> RunResult:
    """Executa o agente sobre um banco limpo e devolve o registro da execução."""
    workspace.reset()
    before = workspace.snapshot()

    started = time.time()
    error: str | None = None
    final = ""
    messages: Sequence[BaseMessage] = []

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt}], "passos": 0},
            {"recursion_limit": recursion_limit},
        )
        messages = result["messages"]
        final = last_text(messages)
    except Exception as exc:  # um crash é um resultado da execução, registrado como tal
        error = f"{type(exc).__name__}: {exc}"

    return RunResult(
        prompt=prompt,
        before=before,
        after=workspace.snapshot(),
        trace=copy.copy(workspace.trace),
        final=final,
        messages=messages,
        error=error,
        seconds=round(time.time() - started, 1),
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
) -> RunResult:
    """Envoltório sincrônico de `arun_task`, para a CLI.

    Em código que já roda dentro de um laço de eventos, como uma célula de notebook, chame
    `arun_task` com `await`.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return event_loop().run_until_complete(
            arun_task(agent, workspace, prompt, recursion_limit)
        )
    raise RuntimeError(
        "há um laço de eventos em execução neste processo. Use `await arun_task(...)` em vez de "
        "`run_task(...)`."
    )
