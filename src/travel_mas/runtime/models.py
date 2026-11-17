"""Carga do cliente de chat a partir do `Context`.

`load_chat_model` instancia o cliente do provedor declarado no `Context`: Ollama, Google ou Groq.
Os três clientes expõem a mesma interface de chat do LangChain.
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


def _groq_raciocina(model: str) -> bool:
    """Modelos do Groq que aceitam `reasoning_effort`."""
    return "gpt-oss" in model or "qwen3" in model


def load_chat_model(context: Context) -> BaseChatModel:
    """Instancia o cliente do provedor declarado no contexto.

    O Ollama Cloud autentica por cabeçalho `Authorization`; um Ollama local dispensa a chave. Os
    dois clientes recebem `Context.request_timeout` como prazo de cada requisição.

    No Ollama, `reasoning` recebe o nível de `Context.reasoning_effort`. O `gpt-oss` ignora
    `think=false` e gera o raciocínio em toda chamada. Com o nível, o cliente guarda o raciocínio
    em `additional_kwargs["reasoning_content"]` e o devolve no campo `thinking` da mensagem na
    chamada seguinte do laço de ferramentas. Um modelo do Ollama sem a capacidade `thinking` recusa
    o nível com `400 "<modelo>" does not support thinking`.

    O cliente do Google vem do extra `google`, e o do Groq, do extra `groq`. Sem o extra, o
    provedor levanta `RuntimeError` com o comando de instalação.

    No Groq, `reasoning_effort` recebe o nível de `Context.reasoning_effort` nos modelos
    `gpt-oss` e `qwen3`, e o raciocínio volta em `additional_kwargs["reasoning_content"]`. Os
    outros modelos do Groq recusam o parâmetro com 400 e não o recebem. O SDK do Groq reintenta
    erros de conexão, 429 e 5xx `Context.retry_attempts - 1` vezes e espera o tempo de
    `retry-after` antes de reintentar um 429.
    """
    if context.provider == "ollama":
        from langchain_ollama import ChatOllama

        client_kwargs: dict = {"timeout": context.request_timeout}
        if not _is_local(context.base_url):
            key = os.environ.get("OLLAMA_API_KEY")
            if not key:
                raise RuntimeError(
                    "OLLAMA_API_KEY não encontrada. Gere uma chave em "
                    "https://ollama.com/settings/keys e defina a variável no arquivo .env ou no "
                    "ambiente. Para um Ollama local, aponte OLLAMA_BASE_URL para o host local."
                )
            client_kwargs["headers"] = {"Authorization": f"Bearer {key}"}

        return ChatOllama(
            model=context.model,
            base_url=context.base_url,
            client_kwargs=client_kwargs,
            reasoning=context.reasoning_effort,
            temperature=context.temperature,
            num_predict=context.max_tokens,
        )

    if context.provider in GOOGLE_PROVIDERS:
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GOOGLE_API_KEY não encontrada. Gere uma chave em "
                "https://aistudio.google.com/apikey e defina a variável no arquivo .env ou no "
                "ambiente."
            )

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise RuntimeError(
                "O provedor Google pede o extra google. Instale-o com uv sync --extra google."
            ) from exc

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
            timeout=context.request_timeout,
            **amostragem,
        )

    if context.provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY não encontrada. Gere uma chave em https://console.groq.com/keys e "
                "defina a variável no arquivo .env ou no ambiente."
            )
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:
            raise RuntimeError(
                "O provedor Groq pede o extra groq. Instale-o com uv sync --extra groq."
            ) from exc

        esforco = context.reasoning_effort if _groq_raciocina(context.model) else None
        return ChatGroq(
            model=context.model,
            api_key=key,
            temperature=context.temperature,
            max_tokens=context.max_tokens,
            reasoning_effort=esforco,
            timeout=context.request_timeout,
            max_retries=context.retry_attempts - 1,
        )

    raise ValueError(
        f"provedor desconhecido: {context.provider!r}. Use 'ollama', 'google' ou 'groq'."
    )


def without_reasoning(model: BaseChatModel) -> BaseChatModel:
    """Cópia do cliente do Ollama com `reasoning=False`, para as chamadas de saída estruturada.

    O Ollama Cloud não aplica o campo `format`, e o esquema chega ao `gpt-oss` como ferramenta. O
    cliente de outro provedor volta sem cópia.
    """
    from langchain_ollama import ChatOllama

    if isinstance(model, ChatOllama):
        return model.model_copy(update={"reasoning": False})
    return model


def transient_errors() -> tuple[type[Exception], ...]:
    """Erros de provedor que um reintento resolve.

    O Ollama Cloud devolve `Internal Server Error (ref: ...)` com status 500 em parte das
    chamadas que levam histórico de tool calling. Do lado do Google,
    `google.genai.errors.ServerError` cobre os 5xx da API. O 429 de cota chega como `ClientError`
    e fica fora da lista.
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


def schema_rejection(exc: Exception) -> str | None:
    """Motivo da recusa quando o provedor rejeitou a chamada de ferramenta pelo esquema.

    O Groq valida os argumentos de uma chamada de ferramenta contra o esquema JSON antes de
    devolvê-la e responde 400 com `code=tool_use_failed` quando a validação falha, por exemplo com
    `null` em um campo de lista. O campo `message` do corpo traz o motivo e a geração recusada.
    Para outros erros, devolve `None`.
    """
    try:
        from groq import BadRequestError
    except ImportError:
        return None
    if not isinstance(exc, BadRequestError):
        return None
    corpo = exc.body if isinstance(exc.body, dict) else {}
    erro = corpo.get("error", corpo)
    if not isinstance(erro, dict) or erro.get("code") != "tool_use_failed":
        return None
    return str(erro.get("message") or exc)


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
