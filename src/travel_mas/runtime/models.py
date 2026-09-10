"""Carga do cliente de chat a partir do `Context`.

`load_chat_model` instancia o cliente do provedor declarado no `Context`. Os dois provedores expõem
a mesma interface de chat do LangChain.
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from .context import Context

LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")

GOOGLE_PROVIDERS = ("google", "gemini")
"""Nomes aceitos para o provedor do Google AI Studio."""


def _is_local(base_url: str) -> bool:
    return any(host in base_url for host in LOCAL_HOSTS)


def _is_gemini_3_or_later(model: str) -> bool:
    """Identifica a família do Gemini que recusa os parâmetros de amostragem."""
    return "gemini-3" in model


def load_chat_model(context: Context) -> BaseChatModel:
    """Instancia o cliente do provedor declarado no contexto.

    O Ollama Cloud autentica por cabeçalho `Authorization`; um Ollama local dispensa a chave.
    """
    if context.provider == "ollama":
        from langchain_ollama import ChatOllama

        client_kwargs = {}
        if not _is_local(context.base_url):
            key = os.environ.get("OLLAMA_API_KEY")
            if not key:
                raise RuntimeError(
                    "OLLAMA_API_KEY não encontrada. Gere uma chave em "
                    "https://ollama.com/settings/keys e defina a variável no arquivo .env ou no "
                    "ambiente. Para um Ollama local, aponte OLLAMA_BASE_URL para o host local."
                )
            client_kwargs = {"headers": {"Authorization": f"Bearer {key}"}}

        return ChatOllama(
            model=context.model,
            base_url=context.base_url,
            client_kwargs=client_kwargs,
            reasoning=False,
            temperature=context.temperature,
            num_predict=context.max_tokens,
        )

    if context.provider in GOOGLE_PROVIDERS:
        from langchain_google_genai import ChatGoogleGenerativeAI

        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GOOGLE_API_KEY não encontrada. Gere uma chave em "
                "https://aistudio.google.com/apikey e defina a variável no arquivo .env ou no "
                "ambiente."
            )

        # A família Gemini 3 recusa temperature, top_p e top_k, e põe o nível de raciocínio no
        # lugar do reasoning do Ollama. O cliente anula temperature nessa família quando o
        # parâmetro não foi declarado, e o mantém no pedido quando foi.
        if _is_gemini_3_or_later(context.model):
            amostragem = {"reasoning_effort": context.reasoning_effort}
        else:
            amostragem = {"temperature": context.temperature}

        return ChatGoogleGenerativeAI(
            model=context.model,
            google_api_key=key,
            max_output_tokens=context.max_tokens,
            **amostragem,
        )

    raise ValueError(f"provedor desconhecido: {context.provider!r}. Use 'ollama' ou 'google'.")


def transient_errors() -> tuple[type[Exception], ...]:
    """Erros de provedor que um reintento resolve.

    O Ollama Cloud devolve `Internal Server Error (ref: ...)` com status 500 em parte das
    chamadas que levam histórico de tool calling. Uma medição de 20 chamadas do mesmo payload,
    com oito mensagens e três pares de `tool_calls` e `ToolMessage`, deu 3 falhas, e as 3 foram
    atendidas no reintento imediato do mesmo conteúdo. O mesmo payload sem histórico de
    ferramentas não falhou em 40 chamadas.

    Do lado do Google, `google.genai.errors.ServerError` cobre os 5xx da API. O 429 de cota chega
    como `ClientError` e fica fora da lista, porque a espera exponencial de três tentativas não
    cobre a janela de reposição da cota.
    """
    tipos: list[type[Exception]] = []
    try:
        from ollama import ResponseError

        tipos.append(ResponseError)
    except ImportError:
        pass
    try:
        from google.genai.errors import ServerError

        tipos.append(ServerError)
    except ImportError:
        pass
    try:
        from httpx import TransportError

        tipos.append(TransportError)
    except ImportError:
        pass
    return tuple(tipos) or (Exception,)


def with_transient_retry(runnable: Runnable, attempts: int = 3) -> Runnable:
    """Reintenta a chamada em erro de provedor, com espera exponencial.

    Aplica-se depois de `bind_tools`, porque o resultado deixa de expor `bind_tools`. Um erro de
    credencial também é um `ResponseError` e consome as tentativas antes de aparecer.
    """
    return runnable.with_retry(
        retry_if_exception_type=transient_errors(),
        stop_after_attempt=attempts,
        wait_exponential_jitter=True,
    )
