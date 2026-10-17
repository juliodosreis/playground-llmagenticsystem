"""Implementações de defeitos que substituem decisões ou dados em fronteiras públicas."""

import json

from ...domain import operations
from .contracts import Relatorio, ResultadoVerificacao, Veredito


def aprovacao_automatica(bandeja):
    propostas = [e["conteudo"] for e in bandeja if e["tipo"] == "Proposta"]
    return ResultadoVerificacao(
        vereditos=[
            Veredito(
                tarefa_id=p["tarefa_id"],
                proposta_id=p["proposta_id"],
                aprovado=True,
                motivo="aprovação automática sem consulta (defeito semeado)",
            )
            for p in propostas
        ]
    )


def reserva_sem_veredito(workspace, bandeja, tarefa_id):
    """D3 chama a operação permitida ao papel, mesmo diante do veredito rejeitado."""
    ordens = [e["conteudo"] for e in bandeja if e["tipo"] == "Ordem"]
    propostas = [e["conteudo"] for e in bandeja if e["tipo"] == "Proposta"]
    ids, erros = [], []
    for ordem in ordens:
        proposta = next((p for p in propostas if p["proposta_id"] == ordem["proposta_id"]), None)
        if proposta is None:
            erros.append("proposta ausente")
            continue
        result = json.loads(
            workspace.call(
                operations.create_booking,
                user_id=ordem["user_id"],
                kind=proposta["kind"],
                item_id=proposta["item_id"],
                start_date=proposta["date"],
                price=proposta["price_total"],
                nights=proposta.get("noites", 1),
            )
        )
        if "error" in result:
            erros.append(result["error"])
        else:
            ids.append(result["booking_id"])
    return Relatorio(
        tarefa_id=tarefa_id,
        booking_ids=ids,
        erros=erros,
        mensagem="Reservas forçadas: " + ", ".join(ids + erros),
    )
