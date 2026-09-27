"""Execução dos mesmos cenários por várias configurações, com os resultados lado a lado.

Uma configuração reúne modelo, estratégia de grafo, fonte das ferramentas e procedimento.
`compare_models` roda cada cenário uma vez por configuração, sobre um `Workspace` próprio de cada
uma, e reduz a execução a quatro medidas: o tempo em segundos, o número de chamadas de
ferramenta, o número de chamadas ao modelo e o hash do estado final do banco. Duas configurações
que terminam com o mesmo hash deixaram o banco igual, por trajetórias que podem ter sido
diferentes.
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
    """Texto de `--modelo` que não nomeia um provedor conhecido, ou configurações repetidas."""


@dataclass(frozen=True)
class ModelSpec:
    """Uma configuração a comparar, com o rótulo que a identifica nas colunas do relatório.

    O contexto traz o modelo, a estratégia do grafo, a fonte das ferramentas e o procedimento.
    """

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


def combine_specs(
    modelos: Sequence[str],
    estrategias: Sequence[str],
    fontes: Sequence[str] | None = None,
    procedimentos: Sequence[str] | None = None,
    **overrides,
) -> list[ModelSpec]:
    """Um spec por combinação de modelo, estratégia, fonte e procedimento, nessa ordem de variação.

    Sem `fontes` ou sem `procedimentos`, cada spec usa o valor padrão de `Context`. O rótulo nomeia
    o que varia entre as colunas: o modelo, a estratégia, a fonte e o procedimento, cada um quando
    há mais de um valor, separados por `/`. Quando nada varia, o rótulo é o modelo. Dois specs com
    o mesmo rótulo levantam `SpecError`.
    """
    variantes = [
        {
            **({} if fonte is None else {"tool_source": fonte}),
            **({} if procedimento is None else {"procedure": procedimento}),
        }
        for fonte in fontes or [None]
        for procedimento in procedimentos or [None]
    ]
    specs = []
    for texto in modelos:
        for estrategia in estrategias:
            for variante in variantes:
                spec = parse_spec(texto, strategy=estrategia, **variante, **overrides)
                eixos = [
                    (len(modelos) > 1, spec.context.model),
                    (len(estrategias) > 1, estrategia),
                    (len(fontes or []) > 1, spec.context.tool_source),
                    (len(procedimentos or []) > 1, spec.context.procedure),
                ]
                partes = [valor for varia, valor in eixos if varia] or [spec.context.model]
                specs.append(ModelSpec(label="/".join(partes), context=spec.context))

    rotulos = [spec.label for spec in specs]
    if len(set(rotulos)) < len(rotulos):
        raise SpecError(f"configurações repetidas na comparação: {', '.join(rotulos)}")
    return specs


@dataclass
class ModelRun:
    """As medidas de uma execução de um cenário por uma configuração."""

    label: str
    seconds: float
    calls: int
    state: str
    error: str | None = None
    model_calls: int = 0
    """Chamadas ao modelo, lidas do campo `passos` do estado final, que as duas estratégias do
    agente incrementam a cada chamada. Um reintento de erro passageiro não conta outra vez."""

    def cell(self) -> str:
        """A célula da coluna: tempo, chamadas de ferramenta e chamadas ao modelo, ou o erro."""
        if self.error:
            return "erro"
        return f"{self.seconds}s / {self.calls} / {self.model_calls}"


@dataclass
class ScenarioComparison:
    """O mesmo cenário rodado por cada configuração."""

    key: str
    name: str
    runs: list[ModelRun]

    def agree(self) -> bool:
        """Verdadeiro quando todas as configurações deixaram o banco no mesmo estado, sem erro."""
        if any(run.error for run in self.runs):
            return False
        return len({run.state for run in self.runs}) == 1


@dataclass
class Comparison:
    """O relatório inteiro: as configurações comparadas e um resultado por cenário."""

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

    def total_model_calls(self, label: str) -> int:
        return sum(
            run.model_calls
            for scenario in self.scenarios
            for run in scenario.runs
            if run.label == label
        )

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

    Cada configuração recebe um `Workspace` próprio, e `run_task` o limpa antes de cada cenário,
    então o hash do estado final depende apenas do que aquela configuração escreveu. Um erro na
    montagem do grafo, como uma chave de API ausente, marca todos os cenários daquela configuração
    e não interrompe as demais.

    `build` recebe o workspace e o contexto de um spec. O padrão monta o agente de viagem sobre o
    provedor, a estratégia, a fonte de ferramentas e o procedimento do contexto.
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
                    model_calls=result.values.get("passos", 0),
                )
            )
        scenarios.append(ScenarioComparison(key=key, name=scenario.name, runs=runs))

    return Comparison(labels=[spec.label for spec in specs], scenarios=scenarios)
