"""Execução repetida de casos e cálculo estrito de pass^k."""

import asyncio
from dataclasses import asdict, dataclass

from ..agents.mas import abuild_graph
from ..runtime import Context, RunResult, Workspace, arun_task
from .casos import Caso, origem, validate_case
from .checks import CheckResult, Evaluation, avaliar


@dataclass
class CaseRun:
    caso: str
    repeticao: int
    config: dict
    avaliacao: Evaluation
    resultado: RunResult | None

    def to_dict(self):
        return {
            "caso": self.caso,
            "repeticao": self.repeticao,
            "config": self.config,
            "avaliacao": self.avaliacao.to_dict(),
            "resultado": self.resultado.to_dict() if self.resultado else None,
        }


async def arun_case(caso: Caso, context: Context, repeticao=1, build=abuild_graph) -> CaseRun:
    result = None
    if caso.pendente:
        evaluation = Evaluation(
            caso.id,
            [
                CheckResult(
                    "decisão pendente",
                    "no_evaluable",
                    origem("R4"),
                    caso.pendente,
                )
            ],
        )
    else:
        workspace = Workspace()
        try:
            validate_case(caso)
            agent = await build(workspace, context)
            limite = (
                min(context.recursion_limit, context.max_rodadas + 6)
                if "D6" in context.defeitos
                else context.recursion_limit
            )
            result = await arun_task(
                agent,
                workspace,
                caso.solicitud,
                limite,
                estado_inicial=caso.estado_inicial,
                tool_faults=caso.tool_faults,
                message_faults=caso.message_faults,
            )
        except Exception as exc:
            evaluation = Evaluation(
                caso.id,
                [
                    CheckResult(
                        "configuração",
                        "no_evaluable",
                        origem(caso.regra_origem[0]),
                        f"{type(exc).__name__}: {exc}",
                    )
                ],
            )
        finally:
            workspace.db.close()
        if result is not None:
            evaluation = avaliar(result, caso)
    return CaseRun(caso.id, repeticao, asdict(context), evaluation, result)


async def arun_cases(casos, context, k=3, jobs=1, on_result=None, build=abuild_graph):
    if k < 1 or jobs < 1:
        raise ValueError("k e jobs devem ser >= 1")
    semaphore = asyncio.Semaphore(jobs)

    async def executar(caso, repeticao):
        async with semaphore:
            run = await arun_case(caso, context, repeticao, build=build)
            if on_result:
                on_result(run)
            return run

    return await asyncio.gather(*(executar(caso, i + 1) for caso in casos for i in range(k)))


def summary(runs: list[CaseRun]) -> dict:
    grupos = {}
    for run in runs:
        key = (run.config["topologia"], tuple(run.config["defeitos"]), run.caso)
        grupos.setdefault(key, []).append(run)
    rows = []
    for (topologia, defeitos, caso), series in grupos.items():
        statuses = [r.avaliacao.status for r in series]
        avaliavel = all(s in ("pass", "fail") for s in statuses)
        rows.append(
            {
                "topologia": topologia,
                "defeitos": list(defeitos),
                "caso": caso,
                "k": len(series),
                "pass": statuses.count("pass"),
                "status": statuses,
                "pass^k": int(all(s == "pass" for s in statuses)) if avaliavel else None,
                "regras_falhas": sorted(
                    {
                        c.regra_origem
                        for r in series
                        for c in r.avaliacao.checks
                        if c.status == "fail"
                    }
                ),
            }
        )
    elegiveis = [r for r in rows if r["pass^k"] is not None]
    return {
        "casos": rows,
        "avaliaveis": len(elegiveis),
        "pass^k": sum(r["pass^k"] for r in elegiveis) / len(elegiveis) if elegiveis else None,
        "nao_avaliaveis": len(rows) - len(elegiveis),
    }
