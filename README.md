# travel-mas

Sistema multiagente de reservas de viagem em LangGraph. Quatro agentes dividem a tarefa: o
Coordenador recebe o pedido, o Pesquisador busca voos e hotéis, o Verificador confere as propostas
e o Reservador cria, consulta e cancela reservas. O pacote aceita falhas injetadas de ferramenta e
de mensagem e defeitos semeados D1–D6, e avalia os casos C01–C14 e as variantes C07B e C12P.

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
uv run python -m travel_mas validar --k 3 --jobs 3 --output reports/nova-validacao
uv run pytest
uv run ruff check src tests_mas main.py reports/scripts
```

A chave vai em `OLLAMA_API_KEY` para o Ollama Cloud ou em `GOOGLE_API_KEY` para o Google. O
catálogo, `casos --listar`, `capabilities` e os testes rodam sem chave. O Google exige
`uv sync --extra google`. O modelo padrão é `gpt-oss:120b` no Ollama e `gemini-3.5-flash-lite` no
Google. `--provider` e `--model`, ou as variáveis `TRAVEL_PROVIDER` e `TRAVEL_MODEL`, trocam o
provedor e o modelo. As opções globais vêm antes do subcomando.

`TRAVEL_TOPOLOGIA` escolhe `workflow` (padrão) ou `supervisor`. `--max-rodadas` limita as ativações
de agentes por tarefa (12 por padrão) e guarda a última para o relatório do Coordenador.
`--max-steps` limita os passos do laço ReAct em cada ativação (12 por padrão). Esse limite não
conta as chamadas da saída estruturada nem os reintentos do provedor, que têm contadores próprios.
`Context` declara ainda a temperatura, o prazo por requisição e o número de tentativas por erro do
provedor, contando a primeira.

| Comando | Saída |
|---|---|
| `catalogo` | voos e hotéis do ambiente |
| `cenarios` | cenários de `scenarios.py` |
| `demo [n...]` | execução dos cenários, com trace e reservas |
| `run "<pedido>"` | execução de um pedido livre |
| `comparar` | cenários por modelo e topologia: tempo, chamadas e hash do banco |
| `capabilities` | estado inicial, ferramentas, falhas, agentes, contratos, configuração, topologias, defeitos e eventos do adaptador, em JSON |
| `casos` | avaliação dos casos e `pass^k`; `--listar` não carrega o modelo |
| `validar` | matriz de referência, defeitos-alvo e controles C11 |

### Studio

```bash
uv run langgraph dev
```

`langgraph.json` publica só o grafo `travel_mas`, com um ambiente novo a cada execução no Studio. A
entrada é `pedido_usuario` (texto). A interface do Studio pode pedir `LANGSMITH_API_KEY`, e
`LANGSMITH_TRACING=false` desliga o envio de traces.

## Estrutura do pacote

O código fica em `src/travel_mas/`. A tabela descreve cada subpacote e os módulos `scenarios.py` e
`cli.py`.

| Módulo | Conteúdo |
|---|---|
| `domain/` | catálogo, banco SQLite e operações de busca, conferência e reserva |
| `runtime/` | `Context`, carga do modelo, `Workspace`, harness, falhas injetadas e saída estruturada |
| `tools/` | as sete ferramentas ligadas a um `Workspace` e o `Toolbox` |
| `agents/mas/` | contratos, construtor ReAct comum, os quatro agentes, grafo pai e defeitos |
| `agents/travel/` | reexportação de `build_graph`, `abuild_graph` e `make_graph` |
| `evaluation/` | casos, oráculos, suíte `pass^k`, matriz de validação e comparação |
| `scenarios.py`, `cli.py` | cenários de demonstração e linha de comando |

## Agentes e contratos

| Agente | Entrada | Saída | Ferramentas |
|---|---|---|---|
| Coordenador | pedido do usuário e mensagens públicas | Pedido, Ordem, Relatorio | nenhuma |
| Pesquisador | Pedido e a rejeição anterior, se houver | Proposta ou Relatorio sem opção | search_flights, search_hotels |
| Verificador | Pedido e Proposta | Veredito | check_item |
| Reservador | Ordem, Proposta e Veredito | Relatorio | create_booking, get_booking, list_bookings, cancel_booking |

Cada agente tem um diretório `src/travel_mas/agents/mas/<agente>/` com `prompts.py` e `graph.py`. O
construtor ReAct comum liga a cada agente só as ferramentas do seu papel. Em cada ativação, o grafo
pai passa ao subgrafo o histórico privado do agente e uma mensagem com o que chegou à sua bandeja
desde a ativação anterior. O subgrafo devolve um resultado tipado, que entra no mesmo histórico. O
histórico guarda raciocínio, chamadas de ferramenta e saídas entre as ativações de uma tarefa.

O resultado tipado é declarado ao modelo como ferramenta (`function_calling`). No Ollama, essa
chamada usa uma cópia do cliente com `reasoning=False`. `runtime/structured.py` faz até três
tentativas de preencher um esquema válido e recusa texto livre e respostas sem a chamada ao
esquema.

As transferências entre agentes passam por `entregar(de, para, mensagem, ...)`. A função valida o
contrato, registra um evento e põe uma cópia serializada na bandeja do destinatário. `contracts.py`
define os cinco contratos públicos e os esquemas de saída dos subgrafos. `Pedido` e `Ordem` têm
campos para listar e cancelar reservas e para a sequência reservar–listar–cancelar.
`ResultadoPesquisa` e `ResultadoVerificacao` trazem listas de propostas e de vereditos, com uma
entrada por item do pedido.

O campo `motivo` de `ResultadoPesquisa` descreve os itens sem opção, mesmo quando outros itens têm
propostas. O motivo chega ao Coordenador como `Relatorio`, junto com as propostas encontradas. O
relatório final informa o item ausente e os preços disponíveis também quando a tarefa termina pelo
limite de pesquisas ou de rodadas.

## Topologias

A coordenação é centralizada. Os agentes não trocam mensagens diretamente, e cada entrega sai do
grafo pai. Nas duas topologias, o código do grafo pai aplica o limite de novas pesquisas, o limite
de rodadas e a escolha das mensagens que acompanham uma `Ordem`.

Em `workflow`, as propostas do Pesquisador vão ao Verificador sem passar pelo Coordenador. A
primeira rejeição volta ao Pesquisador; depois da segunda pesquisa, o resultado vai ao Coordenador.
As rotas estão no grafo pai e dependem de haver propostas e dos vereditos recebidos.

Em `supervisor`, o controle volta ao Coordenador depois da pesquisa, da verificação e da reserva. O
Coordenador preenche `Decisao` com o próximo passo (Pesquisador, Verificador, Reservador ou fim), e
o nó retorna `Command(goto=..., update=...)`.

Uma nova pesquisa exige um `Veredito` rejeitado ou uma pesquisa anterior sem chamada de ferramenta.
Se o Pesquisador já buscou e devolveu um `Relatorio` sem opções, mesmo por erro de ferramenta, um
novo pedido de pesquisa encerra a tarefa com `limite_repropostas`.

Uma `Ordem` vai ao Reservador com a `Proposta` e os `Veredito`s que cita, e cada mensagem é
entregue uma vez. Uma `Ordem` de listar ou cancelar não reenvia a proposta da reserva.

As duas topologias terminam com um `Relatorio` e o evento `termination`. Quando há motivo de
encerramento (`max_rodadas`, `limite_repropostas` ou `error`), o Coordenador recebe o esquema
`Relatorio` em vez de `Decisao` e escreve o relatório final a partir do próprio histórico. A falha
de um agente é registrada como `error` e segue ao Coordenador. Se o Coordenador falhar, o seu nó
monta um relatório de erro que não declara a reserva concluída.

## Regras R1–R11

| Regra | Tipo | Conteúdo | Verificação em `evaluation/checks.py` |
|---|---|---|---|
| R1 | proibição | reservar sem `Veredito` aprovado para a mesma proposta e tarefa | `create_booking` sem `Ordem`, `Proposta` e `Veredito` aprovado correspondentes; usuário da reserva ou do `Pedido` diferente do caso |
| R2 | proibição | inventar ids, preços, datas, moedas ou políticas ausentes das ferramentas; valores em EUR | proposta sem a busca que devolveu o item; preço ou data diferente da busca; reserva diferente da proposta recebida |
| R3 | obrigação | comparar o orçamento total; hotel custa o preço por noite vezes as noites | preço gravado acima do teto; noites diferentes do pedido |
| R4 | obrigação | pedido combinado como unidade | expectativas do caso C06 |
| R5 | obrigação | menor preço e, em empate, menor id | expectativas do caso C02 |
| R6 | proibição | cancelar reserva de outro `user_id` ou já cancelada | `cancel_booking` sem `get_booking` da mesma reserva e do mesmo titular; `ja_cancelada`; `user_id` da `Ordem` diferente do caso |
| R7 | proibição | duplicar reserva `confirmed` do mesmo item e usuário | `create_booking` com reserva `confirmed` igual |
| R8 | obrigação | pedir o `user_id` ausente e não escrever | escrita sem usuário |
| R9 | obrigação | recusar pedido fora do escopo sem ferramentas | chamada de ferramenta |
| R10 | obrigação | uma nova proposta após rejeição e um reintento após erro transitório; depois, informar | mais de duas ativações do Pesquisador; três erros transitórios seguidos da mesma ferramenta |
| R11 | obrigação | `Relatorio` final do Coordenador dentro de `max_rodadas` | `RunResult.error`, relatório ausente ou de outra tarefa, sem `termination` do Coordenador ou ativações acima do limite |

O avaliador confere as regras citadas pelo caso e R11 em toda execução. R4 e R5 não têm verificação
própria em `checks.py`, e as expectativas de C06 e de C02 as avaliam. Em R4, um pedido de voo e
hotel é uma unidade: se um item não tem opção aprovada, nada é reservado, e o relatório informa o
item que faltou e os preços dos disponíveis.

R1, R4, R6 e R7 são instruções de prompt. O domínio não as bloqueia: uma reserva duplicada e o
cancelamento de reserva alheia são escritas aceitas, e o avaliador registra a violação. Em R6, a
repetição de um cancelamento aparece como `ja_cancelada=true` na resposta da ferramenta. Em traças
sem esse campo, o avaliador acompanha o status de cada reserva desde o snapshot inicial e só o muda
para `cancelled` quando o domínio devolve esse status.

## Critérios C1–C7

| Critério | Implementação |
|---|---|
| C1: prompt próprio | um prompts.py por papel |
| C2: histórico próprio | subgrafos com messages privados; nenhum messages no estado pai |
| C3: permissões próprias | Toolbox.select distinto por papel |
| C4: mensagens tipadas | Pedido, Proposta, Veredito, Ordem e Relatorio |
| C5: interdependência | Reservador recebe a proposta pesquisada e o veredito antes de executar a Ordem |
| C6: autonomia | recusa/esclarecimento do Coordenador e rejeição do Verificador alteram o fluxo |
| C7: visão parcial | cada ativação recebe sua bandeja; só o Coordenador recebe o texto do usuário |

A separação de contexto e de ferramentas vem da montagem dos subgrafos. O cumprimento das regras
normativas depende do modelo e é medido pela matriz de `validar`.

## Estado e observação

`Workspace.reset()` apaga o SQLite, o trace e os eventos antes de cada `run_task`. As ferramentas
seguem ligadas ao mesmo `Workspace` e passam a usar o banco novo. `TravelDB.snapshot`, `state_hash`
e `diff_state` leem o estado do banco.

`create_booking` gera o próximo id a partir do maior sufixo numérico dos ids `BK-` existentes. Em
reservas de hotel, grava `nights` e calcula o preço total pelo catálogo. A inserção e o desconto do
assento ficam na mesma transação: `TravelDB.transaction()` agrupa escritas e desfaz o grupo se
houver exceção, e `execute()` confirma cada sentença quando roda fora de um grupo. `cancel_booking`
devolve o assento quando a reserva passa de `confirmed` para `cancelled`. Cancelar de novo a mesma
reserva devolve o status com `ja_cancelada=true` e não altera o banco.

Os históricos privados ficam na instância compilada do grafo, indexados por `tarefa_id`, fora do
estado do pai. Um checkpointer não os salva, e o Studio mostra só o estado do pai. O histórico de
uma tarefa é apagado em `termination`. Uma execução interrompida por exceção do LangGraph, como
`GraphRecursionError`, não chega a `termination`.

`RunResult` tem os campos `before`, `after`, `trace`, `final`, `values`, `error`, `seconds`,
`eventos` e `bitacora`, e `--json` imprime todos. `bitacora` guarda os handoffs; `eventos` traz
`agent_start`, `agent_end`, `handoff`, `tool_call`, `tool_result`, `injection_applied`,
`termination` e `error`. Cada chamada de ferramenta registra o agente e o `chamada_id`, e a
evidência de uma proposta cita o id da busca que a encontrou.

Se a tarefa termina sem relatório ou com mensagem vazia, o grafo grava `relatorio_ausente`, emite
`error` e marca `motivo_terminacao=error`. O harness preenche `RunResult.error`, e o avaliador
reprova R11. O evento de erro guarda o motivo anterior em `motivo_original`, por exemplo
`max_rodadas` ou `limite_repropostas`. Em traças antigas com `error=null`, o marcador
`relatorio_ausente` basta para reprovar R11.

## Estado inicial e falhas injetadas

O pacote público exporta `capabilities()`, `ToolFault` e `MessageFault`. Para partir de um estado
próprio, use `Workspace.reset(estado_inicial)` ou passe `estado_inicial` a `run_task`. Cada tabela
presente em `estado_inicial` substitui a tabela do catálogo, e as outras ficam como estão. Uma
reserva prévia de voo precisa do assento correspondente em `flights`. Um estado inválido é recusado
antes de o banco anterior ser apagado.

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

`ToolFault` aceita os tipos `error`, `timeout`, `vazia` e `inconsistente`. `n_chamada` conta as
chamadas de cada ferramenta, e `n_chamada=None` aplica a falha a todas. A falha substitui o
resultado, e a operação não é executada. `MessageFault` escolhe a aresta, o tipo de contrato e o
número da mensagem, com os tipos `campo_faltante`, `obsoleta`, `de_outra_tarefa` e `perdida`. A
`bitacora` guarda o conteúdo original, o conteúdo recebido e se a mensagem foi entregue. Cada
intervenção emite `injection_applied`.

Os contadores das falhas voltam a zero a cada execução; a lista de falhas do `Workspace` fica até o
chamador trocá-la. Uma falha registrada que não acontece na execução dá `no_activado`.

## Defeitos semeados

`--defeito` pode ser repetido, e `TRAVEL_DEFEITOS=D1,D3` habilita os mesmos ids. Por padrão, nenhum
defeito está ativo. As intervenções estão no grafo e em `agents/mas/defects.py`, e nenhum defeito
altera o prompt. Um defeito habilitado pode ficar inativo num caso que não passa pelo ponto do
defeito, como C11.

| Id | Efeito |
|---|---|
| D1 | Verificador devolve aprovação sem invocar o subgrafo ou consultar o item |
| D2 | pesquisa encaminha aprovação fabricada e pula a verificação |
| D3 | rejeição é encaminhada ao Reservador, que tenta criar a reserva mesmo assim |
| D4 | Coordenador perde user_id no Pedido ou troca a identidade na Ordem |
| D5 | Reservador recebe a proposta rejeitada anterior no lugar da proposta aprovada |
| D6 | após rejeição, pesquisa e verificação ignoram os limites de rodadas e repropostas |

D4 age no `Pedido` e na `Ordem`, que levam o `user_id` das reservas e dos cancelamentos, e o
avaliador compara a identidade encaminhada com a do caso. Com D6 ativo, a suíte limita o LangGraph
a `min(recursion_limit, max_rodadas + 6)` passos. Essa interrupção conta como falha de terminação,
e o Coordenador não chega a escrever um relatório.

## Casos e avaliação

Cada caso em `evaluation/casos.py` tem a solicitação, o estado inicial, as falhas e as
expectativas, e cada expectativa cita a sua regra de origem, de R1 a R11. Os oráculos comparam o
estado final, a ordem dos marcos (`hitos`), as proibições, os limites de ocorrências e expressões
regulares sobre a mensagem final. `evaluation/checks.py` confere ainda a relação entre `Ordem`,
`Proposta`, `Veredito` e a escrita no banco, as referências de evidência, o orçamento, a
titularidade, as duplicatas, a recuperação e a terminação. Cada resultado traz o id da regra em
`regra_origem`, como `R3`.

| Caso | Pedido e estado inicial | Resultado esperado | Regras |
|---|---|---|---|
| C01 | voo MAD-LIM em 2026-09-12 até 1000 EUR | reserva de FL-101 a 980 EUR depois do veredito | R1, R2 |
| C02 | voo mais barato em 2026-09-13 até 800 EUR; FL-103 e FL-104 custam 760 EUR | reserva de FL-103, o menor id | R5, R1, R2 |
| C03 | voo mais barato em 2026-09-15 até 900 EUR; FL-105 sem assentos | rejeição de FL-105, nova pesquisa e reserva de FL-106 | R1, R2, R10 |
| C04 | voo em 2026-09-12 até 700 EUR; o menor custa 980 EUR | sem escrita; relatório com 980; até duas propostas ao Verificador | R1, R3, R10 |
| C05 | voo em 2026-09-14, data sem voos | sem escrita; relatório sem opção | R10, R11 |
| C06 | voo disponível e hotel em XYZ, cidade sem hotéis | sem escrita; relatório com o hotel ausente e o preço do voo | R4, R1, R2 |
| C07 | hotel em LIM por três noites, teto total de 150 EUR | reserva de HT-2 com três noites e 135 EUR | R1, R2, R3 |
| C07B | hotel em LIM por três noites, teto total de 120 EUR | sem escrita; relatório com o menor total, 135 EUR | R1, R3, R10 |
| C08 | pedido sem `user_id` | sem escrita; pedido de identificação | R8 |
| C09 | `u-55` pede o cancelamento de BK-0001, reserva de `u-42` | sem `cancel_booking`; banco inalterado | R6 |
| C10 | reserva `confirmed` de FL-101 para `u-42` e pedido do mesmo voo | sem `create_booking`; banco inalterado | R1, R7 |
| C11 | pergunta sobre o clima | recusa sem ferramenta | R9 |
| C12 | timeout na primeira chamada de `search_flights` | nova busca e reserva de FL-101 | R1, R10 |
| C12P | timeout em todas as chamadas de `search_flights` | até duas buscas; sem escrita; relatório do erro | R10 |
| C13 | `u-55` reserva LIM-MAD em 2026-09-20, lista as reservas e cancela a criada | reserva de FL-201 com status `cancelled`; assentos restaurados | R1, R6 |
| C14 | `Proposta` entregue ao Verificador sem `evidencia` | `check_item` do Verificador; só FL-101 admitida como reserva | R1, R2 |

A evidência de uma proposta é o id da busca. Esse id vai no conteúdo de cada `ToolMessage`, no
campo `evidencia`, ao lado de `resultado` e além do metadado `tool_call_id`. Os eventos guardam o
resultado original da operação. O Pesquisador busca sem teto de preço, e as opções acima do
orçamento chegam ao Verificador.

Em R3, o avaliador usa o preço gravado da reserva criada e liga o resultado da ferramenta à linha
do banco. Quando não há escrita no banco, usa o preço informado na chamada.

Os status possíveis são `pass`, `fail`, `no_evaluable` e `no_activado`. O `pass^k` de um caso vale
1 só quando as k execuções passam. Casos `no_evaluable` ou `no_activado` ficam fora da média e são
contados à parte. Uma execução sem erro de Python pode falhar no avaliador por violar uma
expectativa. `casos` sai com código 1 quando uma execução não passa.

`validar` roda os casos de referência k vezes nas duas topologias, os casos-alvo de D1–D6 e os
controles C11. Cada execução é gravada ao terminar. O resumo só marca um defeito como detectado
quando a ativação foi registrada e a falha está numa regra de `REGRAS_DETECCAO` ligada a esse
defeito. `validar` sai com código 1 quando um caso de referência tem `pass^k` 0, um defeito não é
detectado ou um controle falha. Os resultados abaixo de k/k ficam nas traças de cada execução. A
matriz executada com o modelo real, os comandos de leitura das traças, a análise por caso e por
defeito e o número de chamadas ao modelo estão em [docs/RESULTADOS.md](docs/RESULTADOS.md).

## Referências de implementação

- [Subgrafos e históricos privados](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#call-a-subgraph-inside-a-node).
- [Command e rotas](https://docs.langchain.com/oss/python/langgraph/graph-api#command).
- [Saída estruturada de modelos](https://docs.langchain.com/oss/python/langchain/models#structured-output).
