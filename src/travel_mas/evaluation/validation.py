"""Matriz reproduzível: referência k vezes, defeitos-alvo e controles fora do escopo."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from ..runtime import RunResult, ToolCall
from .casos import CASOS
from .checks import CheckResult, Evaluation, avaliar
from .suite import CaseRun, arun_case, summary


def exigir_ativacao(run):
    """Somente os alvos exigem ativação; os controles mantêm a avaliação normal."""
    if run.resultado is not None:
        run.resultado.injecoes_esperadas = sorted(
            set(run.resultado.injecoes_esperadas + list(run.config["defeitos"]))
        )
        run.avaliacao = avaliar(run.resultado, CASOS[run.caso])
    return run


def reavaliar(output):
    """Reaplica oráculos aos dados capturados; não chama o provedor nem executa agentes."""
    output = Path(output)
    resultados = []
    for path in sorted(output.glob("*.json")):
        raw = json.loads(path.read_text())
        if "avaliacao" not in raw:
            continue
        result = raw.get("resultado")
        if result is not None:
            dados = {
                key: value for key, value in result.items() if key in RunResult.__dataclass_fields__
            }
            dados["trace"] = [ToolCall(**c) for c in dados["trace"]]
            result = RunResult(**dados)
            evaluation = avaliar(result, CASOS[raw["caso"]])
        else:
            evaluation = Evaluation(
                raw["caso"], [CheckResult(**c) for c in raw["avaliacao"]["checks"]]
            )
        run = CaseRun(raw["caso"], raw["repeticao"], raw["config"], evaluation, result)
        if path.name.startswith("defeito-"):
            exigir_ativacao(run)
        path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n")
        resultados.append((path.name.split("-", 1)[0], run, path.name))
    k = max((r.repeticao for f, r, _ in resultados if f == "referencia"), default=1)
    return escrever_relatorio(resultados, output, k)


ALVOS = {
    "D1": ["C03", "C04"],
    "D2": ["C03"],
    "D3": ["C03", "C04"],
    "D4": ["C01", "C09"],
    "D5": ["C03"],
    "D6": ["C04"],
}
REGRAS_DETECCAO = {
    "D1": {"R1", "R3"},
    "D2": {"R1"},
    "D3": {"R1", "R3"},
    "D4": {"R1", "R6"},
    "D5": {"R1"},
    "D6": {"R10", "R11"},
}


def detectou(run, defeito):
    if run.avaliacao.status != "fail" or run.resultado is None:
        return False
    if run.resultado.error and defeito != "D6":
        return False
    if not any(
        e["tipo"] == "injection_applied" and e.get("id") == defeito for e in run.resultado.eventos
    ):
        return False
    regras = {c.regra_origem.rsplit(".", 1)[-1] for c in run.avaliacao.checks if c.status == "fail"}
    if defeito == "D6" and "R10" not in regras:
        rodadas = sum(e["tipo"] == "agent_start" for e in run.resultado.eventos)
        return "R11" in regras and rodadas > run.config["max_rodadas"]
    return bool(regras & REGRAS_DETECCAO[defeito])


async def validar(context, output, k=3, jobs=3, on_result=None):
    if k < 1 or jobs < 1:
        raise ValueError("k e jobs devem ser >= 1")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    planos = []
    for topologia in ("workflow", "supervisor"):
        referencia = replace(context, topologia=topologia, defeitos=())
        for caso in CASOS.values():
            for repeticao in range(1, k + 1):
                planos.append(("referencia", referencia, caso, repeticao))
        for defeito, alvos in ALVOS.items():
            config = replace(referencia, defeitos=(defeito,))
            for key in alvos:
                planos.append(("defeito", config, CASOS[key], 1))
            planos.append(("controle", config, CASOS["C11"], 1))
    semaphore = asyncio.Semaphore(jobs)

    async def executar(fase, config, caso, repeticao):
        async with semaphore:
            run = await arun_case(caso, config, repeticao)
            if fase == "defeito":
                exigir_ativacao(run)
            nome = f"{fase}-{config.topologia}-{'-'.join(config.defeitos) or 'normal'}"
            nome += f"-{caso.id}-{repeticao}.json"
            path = output / nome
            path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n")
            if on_result:
                on_result(fase, run)
            return fase, run, path.name

    resultados = await asyncio.gather(*(executar(*p) for p in planos))
    return escrever_relatorio(resultados, output, k)


def escrever_relatorio(resultados, output, k):
    output = Path(output)
    referencia = [r for f, r, _ in resultados if f == "referencia"]
    resumo = summary(referencia)
    defeitos = []
    for topologia in ("workflow", "supervisor"):
        for defeito in ALVOS:
            alvos = [
                (r, path)
                for f, r, path in resultados
                if f == "defeito"
                and r.config["topologia"] == topologia
                and defeito in r.config["defeitos"]
            ]
            detectado = any(detectou(r, defeito) for r, _ in alvos)
            controles = [
                r
                for f, r, _ in resultados
                if f == "controle"
                and r.config["topologia"] == topologia
                and defeito in r.config["defeitos"]
            ]
            defeitos.append(
                {
                    "topologia": topologia,
                    "defeito": defeito,
                    "detectado": detectado,
                    "controle_passou": bool(controles)
                    and all(r.avaliacao.status == "pass" for r in controles),
                    "controle_ativou_defeito": any(
                        e["tipo"] == "injection_applied" and e.get("id") == defeito
                        for r in controles
                        if r.resultado is not None
                        for e in r.resultado.eventos
                    ),
                    "tracas": [p for _, p in alvos],
                }
            )
    payload = {
        "referencia": resumo,
        "defeitos": defeitos,
        "execucoes": [
            {
                "fase": f,
                "caso": r.caso,
                "repeticao": r.repeticao,
                "topologia": r.config["topologia"],
                "defeitos": r.config["defeitos"],
                "status": r.avaliacao.status,
                "traca": path,
            }
            for f, r, path in resultados
        ],
    }
    previstas = {
        ("referencia", t, (), c, n)
        for t in ("workflow", "supervisor")
        for c in CASOS
        for n in range(1, k + 1)
    }
    previstas |= {
        ("defeito", t, (d,), c, 1)
        for t in ("workflow", "supervisor")
        for d, casos in ALVOS.items()
        for c in casos
    }
    previstas |= {
        ("controle", t, (d,), "C11", 1) for t in ("workflow", "supervisor") for d in ALVOS
    }
    presentes = {
        (f, r.config["topologia"], tuple(r.config["defeitos"]), r.caso, r.repeticao)
        for f, r, _ in resultados
    }
    payload["matriz_completa"] = previstas <= presentes
    payload["execucoes_esperadas"] = len(previstas)
    payload["execucoes_registradas"] = len(resultados)
    (output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    linhas = [
        "# Validação do MAS",
        "",
        f"Referência: {k} execuções por caso e topologia.",
        "Casos com decisão pendente ficam não avaliáveis.",
        "",
        "| Topologia | Caso | Passou | pass^k | Regras com falha |",
        "|---|---|---|---|---|",
    ]
    for row in resumo["casos"]:
        linhas.append(
            f"| {row['topologia']} | {row['caso']} | {row['pass']}/{row['k']} | "
            f"{row['pass^k']} | {', '.join(row['regras_falhas'])} |"
        )
    linhas += [
        "",
        "Resultados abaixo de k/k são instáveis ou falhos nesta configuração.",
        "Os arquivos JSON individuais contêm expectativas e traças completas.",
        "",
        "| Topologia | Defeito | Detectado no alvo | Controle C11 | Ativou no controle |",
        "|---|---|---|---|---|",
    ]
    for row in defeitos:
        linhas.append(
            f"| {row['topologia']} | {row['defeito']} | {row['detectado']} | "
            f"{row['controle_passou']} | {row['controle_ativou_defeito']} |"
        )
    linhas += [
        "",
        "Falha de C11 sem ativação registra falha da resposta do modelo no controle;",
        "não comprova que o defeito habilitado causou essa resposta.",
    ]
    (output / "README.md").write_text("\n".join(linhas) + "\n")
    return payload
