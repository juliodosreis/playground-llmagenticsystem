"""Transferências tipadas por function calling, inclusive no Ollama Cloud."""

import json
from collections.abc import Sequence
from typing import TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from .models import with_transient_retry, without_reasoning

TENTATIVAS_ESQUEMA = 3
Mensagem = TypeVar("Mensagem", bound=BaseModel)


def estruturado(model: BaseChatModel, esquema: type[Mensagem], tentativas: int = 3) -> Runnable:
    """Declara o esquema como ferramenta sobre uma cópia sem raciocínio."""
    saida = without_reasoning(model).with_structured_output(esquema, method="function_calling")
    return with_transient_retry(saida, tentativas)


async def preencher(
    runnable: Runnable,
    mensagens: Sequence[AnyMessage],
    esquema: type[Mensagem],
) -> Mensagem:
    """Recusa texto livre, campos inválidos e respostas sem chamada ao esquema."""
    historico = [
        *mensagens,
        HumanMessage(
            f"Preencha a saída chamando a ferramenta {esquema.__name__}. "
            "Use EXATAMENTE os nomes e tipos dos campos do esquema abaixo, inclusive os campos "
            "aninhados. Não traduza nomes de campos. Use null para objetos opcionais ausentes; "
            "não use {} para eles. Não execute ações novas nesta conversão.\n"
            + json.dumps(esquema.model_json_schema(), ensure_ascii=False)
        ),
    ]
    for _ in range(TENTATIVAS_ESQUEMA):
        try:
            resultado = await runnable.ainvoke(historico)
            if resultado is not None:
                return esquema.model_validate(resultado)
            erro = "a resposta não incluiu a chamada ao esquema"
        except (OutputParserException, ValidationError) as exc:
            erro = str(exc)
        historico.append(
            HumanMessage(
                f"A saída anterior foi recusada: {erro}. Corrija e chame {esquema.__name__}."
            )
        )
    raise RuntimeError(f"o modelo não preencheu o esquema em {TENTATIVAS_ESQUEMA} tentativas")
