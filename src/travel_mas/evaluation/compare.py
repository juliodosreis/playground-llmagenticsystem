"""Execução dos mesmos cenários por vários modelos, com os resultados lado a lado.

`compare_models` roda cada cenário uma vez por modelo, sobre um `Workspace` próprio de cada um, e
reduz a execução a três medidas: o tempo em segundos, o número de chamadas de ferramenta e o hash
do estado final do banco. Dois modelos que terminam com o mesmo hash deixaram o banco igual, por
trajetórias que podem ter sido diferentes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..agents.travel import build_graph
from ..domain import state_hash
from ..runtime import AgentLike, Context, Workspace, run_task
from ..runtime.context import DEFAULT_MODELS
from ..scenarios import SCENARIOS

GraphBuilder = Callable[[Workspace, Context], AgentLike]
"""Assinatura que `compare_models` exige do montador de grafo."""


class SpecError(ValueError):
    """Texto de `--modelo` que não nomeia um provedor conhecido."""


@dataclass(frozen=True)
class ModelSpec:
    """Um modelo a comparar, com o rótulo que o identifica nas colunas do relatório."""

    label: str
    context: Context


def parse_spec(texto: str, **overrides) -> ModelSpec:
    """Lê `provedor` ou `provedor:modelo` e devolve o spec correspondente.

    O identificador do Ollama leva dois-pontos (`gpt-oss:120b`), então a divisão ocorre no
    primeiro separador e o resto do texto é o nome do modelo. Sem modelo, vale o padrão do
    provedor em `DEFAULT_MODELS`.
    """
    provider, _, model = texto.partition(":")
    provider = provider.strip()
    if provider not in DEFAULT_MODELS:
        conhecidos = ", ".join(sorted(DEFAULT_MODELS))
        raise SpecError(f"provedor desconhecido em {texto!r}: {provider!r}. Use {conhecidos}.")

    context = Context(provider=provider, model=model.strip(), **overrides)
    return ModelSpec(label=context.model, context=context)


@dataclass
class ModelRun:
    """As três medidas de uma execução de um cenário por um modelo."""

    label: str
    seconds: float
    calls: int
    state: str
    error: str | None = None

    def cell(self) -> str:
        """A célula da coluna deste modelo: tempo e número de chamadas, ou o erro."""
        if self.error:
            return "erro"
        return f"{self.seconds}s / {self.calls}"


@dataclass
class ScenarioComparison:
    """O mesmo cenário rodado por cada modelo."""

    key: str
    name: str
    runs: list[ModelRun]

    def agree(self) -> bool:
        """Verdadeiro quando todos os modelos deixaram o banco no mesmo estado, sem erro."""
        if any(run.error for run in self.runs):
            return False
        return len({run.state for run in self.runs}) == 1


@dataclass
class Comparison:
    """O relatório inteiro: os modelos comparados e um resultado por cenário."""

    labels: list[str]
    scenarios: list[ScenarioComparison]

    def agreed(self) -> int:
        return sum(1 for scenario in self.scenarios if scenario.agree())

    def total_seconds(self, label: str) -> float:
        total = sum(
            run.seconds
            for scenario in self.scenarios
            for run in scenario.runs
            if run.label == label
        )
        return round(total, 1)

    def errors(self, label: str) -> int:
        return sum(
            1
            for scenario in self.scenarios
            for run in scenario.runs
            if run.label == label and run.error
        )


def compare_models(
    specs: Sequence[ModelSpec],
    keys: Sequence[str],
    build: GraphBuilder = build_graph,
) -> Comparison:
    """Roda os cenários de `keys` por cada spec e reúne as medidas.

    Cada modelo recebe um `Workspace` próprio, e `run_task` o limpa antes de cada cenário, então o
    hash do estado final depende apenas do que aquele modelo escreveu. Um erro na montagem do
    grafo, como uma chave de API ausente, marca todos os cenários daquele modelo e não interrompe
    os demais.

    `build` recebe o workspace e o contexto de um spec. O padrão monta o agente de viagem sobre o
    provedor do contexto; um teste passa um montador que devolve o modelo scriptado.
    """
    agents = {}
    falhas: dict[str, str] = {}
    for spec in specs:
        workspace = Workspace()
        try:
            agents[spec.label] = (build(workspace, spec.context), workspace, spec.context)
        except Exception as exc:
            falhas[spec.label] = f"{type(exc).__name__}: {exc}"

    scenarios = []
    for key in keys:
        scenario = SCENARIOS[key]
        runs = []
        for spec in specs:
            if spec.label in falhas:
                runs.append(ModelRun(spec.label, 0.0, 0, "", falhas[spec.label]))
                continue
            agent, workspace, context = agents[spec.label]
            result = run_task(agent, workspace, scenario.prompt, context.recursion_limit)
            runs.append(
                ModelRun(
                    label=spec.label,
                    seconds=result.seconds,
                    calls=len(result.trace),
                    state=state_hash(result.after),
                    error=result.error,
                )
            )
        scenarios.append(ScenarioComparison(key=key, name=scenario.name, runs=runs))

    return Comparison(labels=[spec.label for spec in specs], scenarios=scenarios)
