"""Estado de uma execução: o banco que os agentes modificam e o trace do que chamaram.

As ferramentas fecham sobre um `Workspace`, e `reset()` troca o banco por um limpo antes de cada
execução, o que permite rodar vários cenários com o mesmo grafo compilado.

O trace é plano e registra, na ordem em que ocorreram, as chamadas que passam por `Workspace.call`
e as que `Workspace.record` recebe.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..domain import Operation, Snapshot, TravelDB
from .faults import MessageFault, ToolFault, validate_faults

agente_atual: ContextVar[str | None] = ContextVar("agente_atual", default=None)
chamada_atual: ContextVar[str | None] = ContextVar("chamada_atual", default=None)


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
    eventos: list[dict[str, Any]] = field(default_factory=list)
    tool_faults: list[ToolFault] = field(default_factory=list)
    message_faults: list[MessageFault] = field(default_factory=list)
    defeitos: tuple[str, ...] = ()
    _tool_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _message_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _ativadas: set[str] = field(default_factory=set, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def reset(self, estado_inicial: dict | None = None) -> None:
        """Descarta o banco e o trace e começa de um ambiente limpo."""
        with self._lock:
            validate_faults(self.tool_faults, self.message_faults)
            novo = TravelDB(estado_inicial)
            self.db.close()
            self.db = novo
            self.trace = []
            self.eventos = []
            self._tool_counts = {}
            self._message_counts = {}
            self._ativadas = set()

    def injection(self, identificador: str, **dados) -> None:
        self._ativadas.add(identificador)
        self.emit("injection_applied", id=identificador, **dados)

    def defect(self, identificador: str, **dados) -> bool:
        if identificador not in self.defeitos:
            return False
        self.injection(identificador, classe="defeito", **dados)
        return True

    def intervir_mensagem(self, de, para, tipo, conteudo):
        """A validação acontece antes deste gancho; a injeção pode quebrar o contrato."""
        chave = f"{de}->{para}:{tipo}"
        self._message_counts[chave] = self._message_counts.get(chave, 0) + 1
        recebido = deepcopy(conteudo)
        for fault in self.message_faults:
            if (
                fault.aresta.replace("→", "->") != f"{de}->{para}"
                or fault.mensagem_tipo != tipo
                or fault.n_mensagem not in (None, self._message_counts[chave])
            ):
                continue
            self.injection(
                fault.id,
                classe="mensagem",
                aresta=f"{de}->{para}",
                falha=fault.tipo,
                mensagem_tipo=tipo,
            )
            if fault.tipo == "perdida":
                return None
            if fault.tipo == "campo_faltante":
                recebido.pop(fault.campo, None)
            elif fault.tipo == "obsoleta":
                recebido["proposta_id"] = "obsoleta:" + recebido.get("proposta_id", "")
            elif fault.tipo == "de_outra_tarefa":
                recebido["tarefa_id"] = "outra-tarefa"
        return recebido

    def emit(self, tipo: str, **dados: Any) -> dict[str, Any]:
        """Registra eventos serializáveis em ordem, sem expor históricos privados."""
        with self._lock:
            evento = {"seq": len(self.eventos) + 1, "tipo": tipo, **dados}
            self.eventos.append(evento)
            return evento

    def call(self, operation: Operation, /, **kwargs: Any) -> str:
        """Executa uma operação sobre o banco desta execução e registra a chamada."""
        with self._lock:
            chamada_id = chamada_atual.get() or f"tool-{len(self.trace) + 1:04d}"
            dados = {
                "agente": agente_atual.get(),
                "ferramenta": operation.__name__,
                "chamada_id": chamada_id,
            }
            self.emit("tool_call", **dados, argumentos=dict(kwargs))
            nome = operation.__name__
            self._tool_counts[nome] = self._tool_counts.get(nome, 0) + 1
            fault = next(
                (
                    f
                    for f in self.tool_faults
                    if f.tool == nome and f.n_chamada in (None, self._tool_counts[nome])
                ),
                None,
            )
            try:
                if fault is not None:
                    self.injection(
                        fault.id,
                        classe="ferramenta",
                        ferramenta=nome,
                        falha=fault.tipo,
                        n_chamada=self._tool_counts[nome],
                    )
                    payload = {
                        "timeout": {"error": "timeout", "transient": True},
                        "error": {"error": "injected_error", "transient": False},
                        "vazia": [],
                        "inconsistente": {"id": "INVALID", "price": -1, "date": "invalid"},
                    }[fault.tipo]
                    if fault.resultado is not None:
                        payload = fault.resultado
                    result = json.dumps(payload, ensure_ascii=False)
                else:
                    result = operation(self.db, **kwargs)
            except Exception as exc:
                self.emit("error", **dados, erro=f"{type(exc).__name__}: {exc}")
                raise
            self.trace.append(ToolCall(operation.__name__, dict(kwargs), result))
            self.emit("tool_result", **dados, resultado=result, executada=fault is None)
        return result

    def record(self, name: str, args: Mapping[str, Any], result: str) -> None:
        """Registra no trace uma chamada que não passa por uma operação do domínio.

        A chamada registrada não altera o banco.
        """
        with self._lock:
            self.trace.append(ToolCall(name, dict(args), result))

    def snapshot(self) -> Snapshot:
        return self.db.snapshot()

    def tool_names(self) -> list[str]:
        return [call.name for call in self.trace]
