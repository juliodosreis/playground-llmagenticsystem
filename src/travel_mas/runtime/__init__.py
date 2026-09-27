"""Infraestrutura compartilhada pelos agentes.

Configuração de execução, carga do modelo, estado de uma execução (banco e trace), harness,
carregador de skills e formatação da saída. Nenhum módulo daqui importa um agente.
"""

from .context import Context
from .display import format_rows, format_trace
from .messages import last_text
from .models import load_chat_model, with_transient_retry, without_reasoning
from .runner import AgentLike, RunResult, arun_task, run_task
from .skills import PROCEDURES, READ_SKILL, Skill, SkillCatalog, build_read_skill, load_skill
from .workspace import ToolCall, Workspace

__all__ = [
    "PROCEDURES",
    "READ_SKILL",
    "AgentLike",
    "Context",
    "RunResult",
    "Skill",
    "SkillCatalog",
    "ToolCall",
    "Workspace",
    "arun_task",
    "build_read_skill",
    "format_rows",
    "format_trace",
    "last_text",
    "load_chat_model",
    "load_skill",
    "with_transient_retry",
    "without_reasoning",
    "run_task",
]
