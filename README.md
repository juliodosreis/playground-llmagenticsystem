# travel-mas

Playground de reservas de viagens em LangGraph. A implementação da branch `mas`, iniciada no tag
`v1.0`, separa a coordenação, a pesquisa, a verificação e a reserva em quatro agentes.
O roteiro está em [PLAN_MAS.md](PLAN_MAS.md). O sistema inclui controles de injeção,
defeitos semeados e avaliação dos casos C01–C14, além das variantes C07B e C12P.
A matriz de validação fica em [reports/mas-validation-final/README.md](reports/mas-validation-final/README.md).

## Execução

Python 3.11 ou posterior e `uv`:

```bash
uv sync
cp .env.example .env
uv run python -m travel_mas catalogo
uv run python -m travel_mas cenarios
uv run python -m travel_mas demo 1
uv run python -m travel_mas --topologia supervisor demo 1
uv run python -m travel_mas --json run "Sou u-42. Liste minhas reservas."
uv run python -m travel_mas comparar --topologia workflow --topologia supervisor 1
uv run python -m travel_mas capabilities
uv run python -m travel_mas casos --listar
uv run python -m travel_mas casos C01 C03 --k 3 --output reports/casos.json
uv run python -m travel_mas --topologia supervisor casos C01 C03 --k 3
uv run python -m travel_mas casos C03 --defeito D1 --k 1
uv run python -m travel_mas validar --k 3 --jobs 3 --output reports/mas-validation
```

Preencha `OLLAMA_API_KEY` para Ollama Cloud ou `GOOGLE_API_KEY` para o Google. O catálogo e a
suíte de testes não precisam de chave. Para Google, instale `uv sync --extra google`.
Os modelos padrão são `gpt-oss:120b` e `gemini-3.5-flash-lite`, respectivamente.
`--provider` e `--model` escolhem outro provedor/modelo; as variáveis correspondentes são
`TRAVEL_PROVIDER` e `TRAVEL_MODEL`. As opções globais ficam antes do subcomando.

`TRAVEL_TOPOLOGIA` escolhe `workflow` (padrão) ou `supervisor`. `--max-rodadas` limita as
ativações dos agentes (12 por padrão) e reserva a última para o relatório do Coordenador.
`--max-steps` limita as chamadas ao modelo dentro de cada ativação ReAct (12 por padrão).
`Context` também declara temperatura, prazo por requisição e tentativas de erros do provedor.

Os eixos antigos `strategy`, `tools` e `procedure`, suas opções e variáveis foram retirados.
As ferramentas agora são locais; o procedimento está nos prompts de cada agente.
`pyyaml` permanece porque a especificação do MAS é um YAML validado pelos testes.

## Agentes e contratos

| Agente | Entrada | Saída | Ferramentas |
|---|---|---|---|
| Coordenador | pedido do usuário e mensagens públicas | Pedido, Ordem, Relatorio | nenhuma |
| Pesquisador | Pedido e eventual rejeição | Proposta ou Relatorio sem opção | search_flights, search_hotels |
| Verificador | Pedido e Proposta | Veredito | check_item |
| Reservador | Ordem, Proposta e Veredito | Relatorio | create_booking, get_booking, list_bookings, cancel_booking |

Cada diretório em `src/travel_mas/agents/mas/<agente>/` contém `prompts.py` e `graph.py`.
O construtor comum de ReAct liga somente as ferramentas daquele papel. O grafo pai chama cada
subgrafo com o histórico privado daquele papel e uma mensagem de entrada com as mensagens da
bandeja pública que chegaram depois da ativação anterior. O resultado devolvido ao pai é tipado
e entra no histórico do papel. O histórico de raciocínio, ferramentas e saídas persiste entre as
ativações de uma mesma tarefa, fora do estado do pai, e é descartado no `termination`.

Todos os handoffs passam por `entregar(de, para, mensagem, ...)`, que valida o contrato,
registra um evento e entrega uma cópia serializada na bandeja do destinatário. `contracts.py`
contém os cinco contratos públicos e os esquemas das respostas dos subgrafos.
`Pedido` e `Ordem` incluem campos para listar/cancelar e para a sequência reservar–listar–cancelar.
`ResultadoPesquisa` e `ResultadoVerificacao` permitem tratar pedidos com mais de um item.

A especificação [spec/mas.yaml](spec/mas.yaml) declara agentes, ferramentas, contratos, estado,
regras R1–R11, recuperação, terminação e procedência. Um teste compara seus nomes com o código.
R1 (veredito correspondente), R6 (titularidade) e R7 (duplicatas) são instruções de prompt.
As operações do domínio não as bloqueiam: o futuro avaliador deve detectar seus descumprimentos.

R4 continua pendente: quando apenas parte de um pedido combinado pode ser atendida, o Coordenador
pede esclarecimento sobre reserva parcial. Esse comportamento provisório ainda não define uma
expectativa de avaliação para C06.

## Critérios C1–C7

| Critério | Implementação |
|---|---|
| C1: prompt próprio | um prompts.py por papel |
| C2: histórico próprio | subgrafos com messages privados; nenhum messages no estado pai |
| C3: permissões próprias | Toolbox.select distinto por papel |
| C4: mensagens tipadas | Pedido, Proposta, Veredito, Ordem e Relatorio |
| C5: interdependência | Reserva recebe a proposta pesquisada e o veredito antes de executar a Ordem |
| C6: autonomia | recusa/esclarecimento do Coordenador e rejeição do Verificador alteram o fluxo |
| C7: visão parcial | cada ativação recebe sua bandeja; só o Coordenador recebe o texto do usuário |

A divisão de contexto e ferramentas é imposta pela montagem dos subgrafos. A adesão dos modelos
às regras normativas depende da execução e será medida pela matriz de avaliação do plano.
Testes com respostas scriptadas verificam a estrutura e os desvios de fluxo; não medem a taxa de
acerto de um modelo real.

## Topologias

`workflow` encaminha propostas do Pesquisador diretamente ao Verificador. A primeira rejeição
retorna ao Pesquisador; depois da segunda pesquisa, o resultado segue ao Coordenador. As rotas
são declaradas no grafo pai e dependem da presença de propostas e dos vereditos recebidos.

`supervisor` devolve o controle ao Coordenador após a pesquisa e a verificação. O Coordenador
preenche `Decisao` para escolher Pesquisador, Verificador, Reservador ou fim, e o nó retorna
`Command(goto=..., update=...)`. Os limites de rodadas e de novas pesquisas também se aplicam.

As duas topologias terminam com `Relatorio` e evento `termination`. Uma nova pesquisa exige um
`Veredito` rejeitado; depois de um `Relatorio` sem opções, inclusive por erro de ferramenta, o
pedido de pesquisa encerra a tarefa com `limite_repropostas`. Com um motivo de encerramento
(`max_rodadas`, `limite_repropostas` ou `error`), o Coordenador é chamado com o esquema
`Relatorio` em vez de `Decisao` e escreve o relatório final sobre o próprio histórico. Uma falha
de agente é registrada como `error` e encaminhada ao Coordenador. Se o próprio Coordenador
falhar, seu nó gera um relatório de erro local, sem afirmar que a reserva foi concluída.

Uma `Ordem` segue ao Reservador com a `Proposta` e os `Veredito`s que ela referencia, e cada
mensagem é entregue uma vez. Uma `Ordem` de listar ou cancelar não reenvia a proposta da reserva.

## Estado e observação

`Workspace.reset()` limpa o SQLite, o trace e os eventos antes de cada `run_task`. As ferramentas
continuam ligadas ao mesmo Workspace e passam a operar sobre o banco novo. `TravelDB.snapshot`,
`state_hash` e `diff_state` continuam disponíveis. Reservas de hotel armazenam `nights`, e
`create_booking` calcula o preço total a partir do catálogo.

`RunResult` contém `before`, `after`, `trace`, `final`, `values`, `error`, `seconds`, `eventos` e
`bitacora`. `--json` imprime esses campos. `bitacora` contém os handoffs; `eventos` inclui
`agent_start`, `agent_end`, `handoff`, `tool_call`, `tool_result`, `termination` e `error`.
Cada chamada de ferramenta registra o agente e o `chamada_id`; a evidência da proposta deve
referenciar o id da chamada de busca.

O adaptador expõe `capabilities()`, `ToolFault` e `MessageFault` pelo pacote público. Para
semear um estado, use `Workspace.reset(estado_inicial)` ou passe `estado_inicial` a `run_task`.
Cada tabela explicitada substitui aquela tabela inteira; as demais mantêm o catálogo padrão.
Reservas prévias devem vir acompanhadas dos assentos correspondentes em `flights`.
Um estado inválido é recusado antes de descartar o banco anterior.

```python
from travel_mas import Context, Workspace, ToolFault, build_graph, run_task

workspace = Workspace()
agent = build_graph(workspace, Context())
result = run_task(
    agent, workspace,
    "Sou u-42. Reserve MAD-LIM em 2026-09-12 por até 1000 EUR.",
    tool_faults=[ToolFault(tool="search_flights", tipo="timeout", n_chamada=1)],
)
```

`ToolFault` aceita `error`, `timeout`, `vazia` e `inconsistente`. A chamada ordinal é contada por
ferramenta; `n_chamada=None` repete a falha em todas as chamadas. Uma falha substitui o resultado
sem executar a operação. `MessageFault` seleciona aresta, tipo de contrato e número da mensagem:
`campo_faltante`, `obsoleta`, `de_outra_tarefa` ou `perdida`. A bitácora mantém conteúdo original,
conteúdo recebido e indicação de entrega. Cada intervenção emite `injection_applied`.
Falhas e seus contadores reiniciam a cada execução; o registro de falhas do Workspace permanece
até o chamador substituí-lo. Falhas registradas que não aparecem na execução geram `no_activado`.
Defeitos habilitados podem permanecer inativos em casos que não os exercitam, como C11; os testes
alvo da matriz verificam explicitamente a ativação antes de declarar detecção.

## Defeitos semeados

`--defeito` é repetível; `TRAVEL_DEFEITOS=D1,D3` configura os mesmos ids. O padrão não habilita
nenhum. As intervenções estão no grafo e em `agents/mas/defects.py`, não em pedidos ao modelo.

| Id | Efeito |
|---|---|
| D1 | Verificador devolve aprovação sem invocar o subgrafo ou consultar o item |
| D2 | pesquisa encaminha aprovação fabricada e salta a verificação |
| D3 | rejeição é encaminhada ao Reservador, que tenta criar a reserva mesmo assim |
| D4 | Coordenador perde user_id no Pedido ou troca a identidade na Ordem |
| D5 | Reservador recebe a proposta rejeitada anterior no lugar da proposta aprovada |
| D6 | após rejeição, pesquisa e verificação ignoram os limites de rodadas e repropostas |

D4 cobre tanto Pedido quanto Ordem para exercitar reservas e cancelamentos. O avaliador compara
a identidade encaminhada com a solicitação do caso. D6 ainda fica sujeito ao watchdog externo do
harness: a suíte limita o LangGraph a `min(recursion_limit, max_rodadas + 6)`. Uma interrupção pelo
harness é falha de terminação, sem relatório de sucesso do Coordenador.

## Casos e avaliação

`evaluation/casos.py` contém solicitação, estado inicial, falhas e expectativas com origem em
`spec/mas.yaml`. Os oráculos comparam estado final, subsequência ordenada de hitos, proibições,
limites de ocorrências e expressões simples sobre a mensagem. `evaluation/checks.py` também
confere relações entre Ordem, Proposta, Veredito e a escrita observada, referências de evidência,
orçamento, titularidade, duplicação, recuperação e terminação. Cada resultado traz `regra_origem`.

A evidência da proposta é o identificador da busca. Esse id aparece explicitamente no conteúdo
de cada ToolMessage como `evidencia`, junto de `resultado`, pois nem todo transporte envia o
metadado `tool_call_id` ao modelo. Os eventos guardam o resultado original da operação.
O Pesquisador busca sem teto para mostrar opções acima do orçamento ao Verificador.

Os resultados possíveis são `pass`, `fail`, `no_evaluable` e `no_activado`. `pass^k` de um caso é
1 somente quando todas as k execuções passam. Casos não avaliáveis ou com falhas não ativadas
ficam fora da média e aparecem contados separadamente. Uma execução sem erro de Python pode
falhar no avaliador por violar uma expectativa. O comando `casos` devolve código 1 quando alguma
execução não passa; `validar` também aponta defeitos não detectados ou controles com falha.

C06 permanece `no_evaluable` por R4. C07 verifica três noites dentro do teto total; C07B usa um
teto menor que o total mais barato para detectar confusão entre preço por noite e total. Para
igual duração, um hotel de menor preço por noite sempre tem menor total; a descrição original do
plano não pode produzir a inversão de ordem que sugeria. C12P exercita timeout persistente.
C14 admite recusa ou consulta adicional, com reserva somente quando houver evidência válida.

`validar` roda a referência k vezes em ambas as topologias, os alvos D1–D6 e controles C11.
Cada execução é salva assim que termina. O resumo marca defeito detectado somente quando há
ativação registrada e falha de uma regra pertinente ao defeito. Resultados abaixo de k/k são
documentados com seus traces; a execução da matriz não presume estabilidade do LLM.

## Testes e Studio

```bash
uv run pytest
uv run ruff check src tests_mas
uv run langgraph dev
```

A suíte versionável fica em `tests_mas/` (70 testes sem LLM nesta etapa).
Na primeira entrega, o cenário 1 passou uma vez em cada topologia com Ollama `gpt-oss:120b`: reserva de
`FL-101` para `u-42`, verificação antes da escrita e consumo de um assento. As duas execuções
estão em [reports/mas-smoke.json](reports/mas-smoke.json). Esses arquivos são históricos, anteriores à exposição explícita do id de evidência.
A validação atual usa `mas-validation-final`; `mas-validation` e `mas-followup` preservam os ensaios anteriores. Os testes locais antigos em `tests/`, que já eram
ignorados pelo Git e dependem dos eixos removidos, foram preservados e não entram na nova suíte.
Os testes MAS usam modelo scriptado e ferramentas reais sobre SQLite, sem chamadas ao provedor.

`langgraph.json` publica apenas `travel_mas`, com um ambiente novo por execução do Studio.
O estado de entrada tem `pedido_usuario` (texto). Os checkpoints não contêm os históricos privados
dos agentes. A interface do Studio pode exigir `LANGSMITH_API_KEY`; `LANGSMITH_TRACING=false`
desativa o envio de traces.

## Referências de implementação

- [Subgrafos e históricos privados](https://docs.langchain.com/oss/python/langgraph/use-subgraphs).
- [Command e rotas](https://docs.langchain.com/oss/python/langgraph/graph-api).
- [Saída estruturada de modelos](https://docs.langchain.com/oss/python/langchain/models).

No Ollama Cloud, o esquema é declarado como ferramenta por `function_calling` sobre a cópia do
cliente com `reasoning=False`. `runtime/structured.py` mantém até três tentativas de preencher
um esquema válido; texto livre ou resposta sem a chamada ao esquema não são aceitos.
