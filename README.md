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

R1 (reserva com veredito aprovado da mesma proposta), R6 (titularidade e cancelamento único) e R7
(duplicatas) são instruções de prompt. O domínio não as bloqueia, e `evaluation/checks.py` registra
as violações. Em R6, o avaliador reprova o cancelamento sem `get_booking` da mesma reserva e do
mesmo titular e o cancelamento de uma reserva já `cancelled`. A repetição aparece como
`ja_cancelada=true` na resposta da ferramenta. Em traças sem esse campo, o avaliador acompanha o
status de cada reserva desde o snapshot inicial e só o muda para `cancelled` quando o domínio
devolve esse status.

R4 trata um pedido de voo e hotel como uma unidade: se um item não tem opção aprovada, nada é
reservado, e o relatório informa o item que faltou e os preços dos disponíveis. R4 é uma instrução
ao Coordenador, sem bloqueio no código, e o caso C06 a avalia.

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

C06 pede um voo disponível e um hotel inexistente e não admite escrita; o relatório deve citar o
hotel ausente e o preço do voo. C07 confere três noites dentro do teto total. C07B usa um teto
menor que o total mais barato, para detectar a troca do preço por noite pelo preço total. C12P
aplica timeout em todas as chamadas de `search_flights`. C14 aceita recusa ou nova consulta e só
admite reserva depois do `check_item` do Verificador.

`validar` roda os casos de referência k vezes nas duas topologias, os casos-alvo de D1–D6 e os
controles C11. Cada execução é gravada ao terminar. O resumo só marca um defeito como detectado
quando a ativação foi registrada e a falha está numa regra de `REGRAS_DETECCAO` ligada a esse
defeito. `validar` sai com código 1 quando um caso de referência tem `pass^k` 0, um defeito não é
detectado ou um controle falha. Os resultados abaixo de k/k ficam nas traças de cada execução.

## Evidência com o modelo real

A matriz `validar --k 3 --jobs 3` rodou com `gpt-oss:120b` no Ollama Cloud, sobre uma árvore sem
alterações locais. As traças, o `summary.json` e o `manifest.json` ficam fora do repositório. O
manifesto registra a versão medida, `codigo_modificado: false`, o SHA-256 de 51 arquivos e o plano
das 126 execuções.

| Fase | Execuções | Resultado |
|---|---|---|
| referência | 96: 16 casos, k=3, duas topologias | 31 de 32 combinações com 3/3 |
| defeitos-alvo | 18: D1–D6 nos casos de `ALVOS` | D1–D6 detectados em workflow e em supervisor |
| controles C11 | 12: um por defeito e topologia | 12 de 12 aprovadas, sem ativação do defeito |

Só C06 em supervisor ficou abaixo de 3/3, com 2 de 3. Na execução reprovada, o Verificador recebeu
`Internal Server Error` do Ollama Cloud nas três tentativas. A execução terminou sem escrita, com
`motivo_terminacao=error` e um relatório do Coordenador com o voo FL-101 a 980 EUR e o hotel
ausente. O avaliador reprova R11 quando há `RunResult.error`.

Nas execuções `defeito-*`, `fail` significa que o avaliador reprovou a execução com o defeito
ativo, e a detecção conta quando a falha está numa regra de `REGRAS_DETECCAO`. D1 é detectado em
C03. Em C04, o Coordenador recusou a aprovação automática: a execução passou em workflow e ficou
`no_activado` em supervisor. D6 terminou com `GraphRecursionError` do limite do harness nas duas
topologias e foi reprovado por R10 e R11.

### Chamadas ao modelo

As traças não registram as chamadas ao modelo. Os números desta seção saem das ativações e das
chamadas de ferramenta registradas nas 126 traças da matriz.

Cada ativação percorre `pensar`, `executar` e `concluir` (`agents/mas/agent.py`). `pensar` chama o
modelo uma vez por rodada de ferramentas e mais uma para a resposta final, e `concluir` faz outra
chamada para preencher o contrato por `function_calling`. Uma ativação sem ferramenta faz duas
chamadas. Com `n` chamadas de ferramenta, faz de três a `n + 2`: três quando o modelo pede todas
numa rodada, `n + 2` quando pede uma por rodada. Em `supervisor`, o Coordenador é ativado depois de
cada agente para preencher `Decisao`. Em C01, a sequência de ativações foi esta, com as chamadas de
ferramenta entre parênteses:

```
workflow:
  coordenador → pesquisador(1) → verificador(1) → coordenador → reservador(3) → coordenador
supervisor:
  coordenador → pesquisador(1) → coordenador → verificador(1) → coordenador → reservador(3)
  → coordenador
```

C01 custa de 15 a 17 chamadas ao modelo em workflow e de 17 a 19 em supervisor. Por fase, as 126
execuções somam:

| Fase | Execuções | Ativações | Chamadas de ferramenta | Chamadas ao modelo |
|---|---|---|---|---|
| referência | 96 | 500 | 349 | 1223–1349 |
| defeitos-alvo | 18 | 135 | 64 | 323–334 |
| controles C11 | 12 | 12 | 0 | 24 |
| total | 126 | 647 | 413 | 1570–1707 |

Na fase de referência, a média foi de 4,9 ativações por execução em workflow e 5,5 em supervisor,
ou de 12,7 a 14,1 chamadas ao modelo por execução. Uma tanda de seis execuções de referência fica
entre 76 e 84 chamadas. Os números não incluem os reintentos de `with_transient_retry` após erro do
provedor nem os de `preencher` após saída inválida, que não aparecem nos eventos.

## Leitura das traças

Os scripts de `reports/scripts/` leem as traças sem executar agentes. `resumo.py` imprime o status
e os checks com falha de cada traça e ignora `summary.json` e `manifest.json`. `eventos.py` imprime
a sequência de handoffs e chamadas de uma traça. `ids.py` conta os formatos de `item_id` nos
diretórios recebidos, ou nos subdiretórios do diretório atual quando não recebe argumentos.
`tanda.py` imprime o plano de uma tanda; para chamar o provedor, exige `--autorizar-provedor`,
aceita até seis execuções e recusa um diretório que já existe.

`reavaliar_integridade.py` reavalia traças salvas com duas versões do avaliador: a de `--baseline`,
uma referência do Git, e a atual, sobre os casos atuais. A saída mostra, por diretório, os status
antes e depois, os checks que mudaram e os hashes das fontes e das traças lidas. O script exige um
arquivo de saída novo e não altera as traças.

```bash
uv run --offline python reports/scripts/resumo.py reports/nova-validacao/*.json
uv run --offline python reports/scripts/ids.py reports/nova-validacao
uv run --offline python reports/scripts/tanda.py reports/nova-tanda --casos C06 --k 3
uv run --offline python reports/scripts/reavaliar_integridade.py reports/nova-validacao \
  --baseline HEAD --output reports/nova-revisao/summary.json
```

## Referências de implementação

- [Subgrafos e históricos privados](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#call-a-subgraph-inside-a-node).
- [Command e rotas](https://docs.langchain.com/oss/python/langgraph/graph-api#command).
- [Saída estruturada de modelos](https://docs.langchain.com/oss/python/langchain/models#structured-output).
