"""Estado de uma execução: o banco que os agentes modificam e o trace do que chamaram.

As ferramentas fecham sobre um `Workspace`, e `reset()` troca o banco por um limpo antes de cada
execução, o que permite rodar vários cenários com o mesmo grafo compilado.

O trace é plano e registra toda chamada que passa por `Workspace.call`, na ordem em que ocorreram.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain import Operation, Snapshot, TravelDB


@dataclass(frozen=True)
class ToolCall:
    """Uma chamada registrada: nome, argumentos nomeados e resultado devolvido."""

    name: str
    args: Mapping[str, Any]
    result: str

    def signature(self) -> str:
        pairs = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.name}({pairs})"


@dataclass
class Workspace:
    """Banco e trace de uma execução."""

    db: TravelDB = field(default_factory=TravelDB)
    trace: list[ToolCall] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def reset(self) -> None:
        """Descarta o banco e o trace e começa de um ambiente limpo."""
        with self._lock:
            self.db.close()
            self.db = TravelDB()
            self.trace = []

    def call(self, operation: Operation, /, **kwargs: Any) -> str:
        """Executa uma operação sobre o banco desta execução e registra a chamada."""
        with self._lock:
            result = operation(self.db, **kwargs)
            self.trace.append(ToolCall(operation.__name__, dict(kwargs), result))
        return result

    def record(self, name: str, args: Mapping[str, Any], result: str) -> None:
        """Registra no trace uma chamada que não passa por uma operação do domínio.

        Usado por `read_skill`, que lê o corpo de uma skill e não toca o banco.
        """
        with self._lock:
            self.trace.append(ToolCall(name, dict(args), result))

    def snapshot(self) -> Snapshot:
        return self.db.snapshot()

    def tool_names(self) -> list[str]:
        return [call.name for call in self.trace]
