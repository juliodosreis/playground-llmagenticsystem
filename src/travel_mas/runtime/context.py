"""Configuração de execução do agente.

`Context` reúne provedor, modelo, orçamento de geração e limites do laço. Os valores padrão vêm de
variáveis de ambiente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


DEFAULT_MODELS = {
    "ollama": "gpt-oss:120b",
    "google": "gemini-3.5-flash-lite",
    "gemini": "gemini-3.5-flash-lite",
}
"""Modelo de cada provedor, usado quando `TRAVEL_MODEL` não está definida."""


@dataclass(kw_only=True)
class Context:
    """Parâmetros de uma execução do agente."""

    provider: str = field(default_factory=lambda: _env("TRAVEL_PROVIDER", "ollama"))
    """Provedor do modelo: `ollama` ou `google`, que também atende por `gemini`."""

    model: str = field(default_factory=lambda: _env("TRAVEL_MODEL", ""))
    """Identificador do modelo no provedor escolhido.

    Vazio resolve para `DEFAULT_MODELS[provider]`, então `Context(provider="google")` já vem com um
    modelo do Gemini. Um identificador do Ollama passado ao provedor Google chega a ele como está.
    """

    topologia: str = field(default_factory=lambda: _env("TRAVEL_TOPOLOGIA", "workflow"))
    """Coordenação: workflow (rotas fixas) ou supervisor (rotas do Coordenador)."""

    max_rodadas: int = 12
    """Ativações de agentes, reservando a última para o relatório do Coordenador."""

    defeitos: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            d.strip() for d in _env("TRAVEL_DEFEITOS", "").split(",") if d.strip()
        )
    )

    base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "https://ollama.com"))
    """Endpoint do Ollama. O padrão é o Ollama Cloud, que exige `OLLAMA_API_KEY`."""

    temperature: float = 0.0
    """Amostragem do modelo. A família Gemini 3 a recusa, e `load_chat_model` não a envia lá."""

    reasoning_effort: str = "low"
    """Nível de raciocínio do modelo: `low`, `medium` ou `high`.

    O Ollama o recebe como `reasoning` do `ChatOllama`, e o `gpt-oss` aceita esses três níveis. A
    família Gemini 3 o recebe como `reasoning_effort`, que o cliente do Google aceita também pelo
    nome `thinking_level`. No Ollama, os tokens do raciocínio contam em `max_tokens`.
    """

    max_tokens: int = 1200

    max_steps: int = 12
    """Chamadas ao modelo antes de a rota encerrar o laço."""

    recursion_limit: int = 50
    """Teto de supersteps do LangGraph. Estourá-lo levanta `GraphRecursionError`."""

    request_timeout: float = 120.0
    """Segundos de espera por uma resposta do provedor.

    Esgotado o prazo, o cliente levanta `httpx.TimeoutException`, que `with_transient_retry`
    reintenta.
    """

    retry_attempts: int = 3
    """Tentativas por chamada ao modelo, contando a primeira, em erro passageiro do provedor."""

    def __post_init__(self) -> None:
        """Preenche o modelo com o padrão do provedor quando nenhum foi declarado."""
        if not self.model:
            self.model = DEFAULT_MODELS.get(self.provider, "")
        if self.topologia not in ("workflow", "supervisor"):
            raise ValueError(f"topologia desconhecida: {self.topologia!r}")
        if self.max_rodadas < 2 or self.max_steps < 1:
            raise ValueError("max_rodadas deve ser >= 2 e max_steps >= 1")
        from .faults import DEFEITOS

        if set(self.defeitos) - set(DEFEITOS):
            raise ValueError(f"defeitos desconhecidos: {self.defeitos}")
        self.defeitos = tuple(sorted(set(self.defeitos)))
