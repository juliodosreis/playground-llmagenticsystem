"""Infraestrutura compartilhada pelos agentes.

Configuração de execução, carga do modelo, estado de uma execução (banco e trace), harness e
formatação da saída. Nenhum módulo daqui importa um agente.
"""

from .context import Context
from .display import format_rows, format_trace
from .messages import last_text
from .models import load_chat_model, with_transient_retry
from .runner import AgentLike, RunResult, arun_task, run_task
from .workspace import ToolCall, Workspace

__all__ = [
    "AgentLike",
    "Context",
    "RunResult",
    "ToolCall",
    "Workspace",
    "arun_task",
    "format_rows",
    "format_trace",
    "last_text",
    "load_chat_model",
    "with_transient_retry",
    "run_task",
]
