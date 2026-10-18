# travel-mas

Playground de reservas de viagens em LangGraph, com coordenação, pesquisa, verificação e reserva
em quatro agentes.
O sistema inclui controles de injeção, defeitos semeados e avaliação dos casos C01–C14, além das
variantes C07B e C12P.

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
```

Preencha `OLLAMA_API_KEY` para Ollama Cloud ou `GOOGLE_API_KEY` para o Google. O catálogo e a
suíte de testes não precisam de chave. Para Google, instale `uv sync --extra google`.
Os modelos padrão são `gpt-oss:120b` e `gemini-3.5-flash-lite`, respectivamente.
`--provider` e `--model` escolhem outro provedor/modelo; as variáveis correspondentes são
`TRAVEL_PROVIDER` e `TRAVEL_MODEL`. As opções globais ficam antes do subcomando.

`TRAVEL_TOPOLOGIA` escolhe `workflow` (padrão) ou `supervisor`. `--max-rodadas` limita as
ativações dos agentes (12 por padrão) e reserva a última para o relatório do Coordenador.
`--max-steps` limita as etapas de pensamento do laço ReAct por ativação (12 por padrão) e não
conta requisições à API: a conversão para saída estruturada e os reintentos do provedor têm
contadores próprios. `Context` também declara temperatura, prazo por requisição e tentativas de
erros do provedor, contando a primeira chamada.

| Comando | Saída |
|---|---|
| `catalogo` | voos e hotéis do ambiente |
| `cenarios` | cenários de `scenarios.py` |
| `demo [n...]` | execução dos cenários, com trace e reservas |
| `run "<pedido>"` | execução de um pedido livre |
| `comparar` | cenários por modelo e topologia: tempo, chamadas e hash do banco |
| `capabilities` | estado inicial, ferramentas, falhas, agentes, contratos, defeitos e eventos do adaptador, em JSON |
| `casos` | avaliação dos casos e `pass^k`; `--listar` não carrega o modelo |
| `validar` | matriz de referência, defeitos-alvo e controles C11 |

## Estrutura do pacote

O pacote fica em `src/travel_mas/`. Fora dele, `spec/mas.yaml` declara agentes, ferramentas,
contratos, estado do pai, regras R1–R11, recuperação, terminação e procedência.

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
`ResultadoPesquisa` e `ResultadoVerificacao` levam listas de propostas e de vereditos, uma
entrada por item do pedido.

Um teste compara os nomes de [spec/mas.yaml](spec/mas.yaml) com o código.
R1 (veredito correspondente), R6 (titularidade e cancelamento único) e R7 (duplicatas) são
instruções de prompt. As operações do domínio não as bloqueiam, e `evaluation/checks.py` detecta
seus descumprimentos. Em R6, o avaliador reprova o cancelamento sem `get_booking` da mesma
reserva e titular e o cancelamento de uma reserva já `cancelled`: a resposta com
`ja_cancelada=true` ou, em traças sem o marcador, o estado seguido desde o snapshot inicial, que
passa a `cancelled` só quando o domínio devolve esse status.

R4 trata o pedido combinado como uma unidade: quando um item não tem opção aprovada, nenhum item
é reservado, e o relatório informa o item que falhou e os disponíveis com preço. É uma instrução
do Coordenador, sem bloqueio em código; C06 a avalia.

O campo `motivo` de `ResultadoPesquisa` descreve os itens sem opção, inclusive quando há
propostas para outros itens. Esse motivo segue ao Coordenador como `Relatorio`, acompanhado
das propostas encontradas. O fechamento informa o item ausente e os preços das opções
disponíveis também quando a execução termina por limite de pesquisas ou de rodadas.

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

A divisão de contexto e ferramentas é imposta pela montagem dos subgrafos. A adesão dos modelos
às regras normativas depende da execução e é medida pela matriz de `validar`.
Testes com respostas scriptadas verificam a estrutura e os desvios de fluxo; não medem a taxa de
acerto de um modelo real.

A coordenação é centralizada. Os agentes não endereçam mensagens entre si: o grafo pai faz
cada entrega. Em `workflow`, a passagem da pesquisa à verificação é uma rota fixa; em
`supervisor`, o Coordenador escolhe o próximo agente. Nas duas topologias, o grafo pai aplica em
código o limite de novas pesquisas, o limite de rodadas e a seleção das mensagens que acompanham
uma `Ordem`.

## Topologias

`workflow` encaminha propostas do Pesquisador ao Verificador, sem passar pelo Coordenador. A
primeira rejeição retorna ao Pesquisador; depois da segunda pesquisa, o resultado segue ao
Coordenador. As rotas são declaradas no grafo pai e dependem da presença de propostas e dos
vereditos recebidos.

`supervisor` devolve o controle ao Coordenador após a pesquisa e a verificação. O Coordenador
preenche `Decisao` para escolher Pesquisador, Verificador, Reservador ou fim, e o nó retorna
`Command(goto=..., update=...)`. Os limites de rodadas e de novas pesquisas também se aplicam.

As duas topologias terminam com `Relatorio` e evento `termination`. Uma nova pesquisa exige um
`Veredito` rejeitado ou uma pesquisa anterior sem chamada de ferramenta. Depois de um `Relatorio`
sem opções com busca executada, inclusive com erro de ferramenta, o pedido de pesquisa encerra a
tarefa com `limite_repropostas`. Com um motivo de encerramento
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

`create_booking` usa o maior sufixo numérico dos ids `BK-` existentes para gerar o próximo id.
A inserção e o desconto de assento pertencem à mesma transação. `TravelDB.transaction()` agrupa
escritas com rollback em caso de exceção; `execute()` confirma cada sentença apenas fora desse
grupo. `cancel_booking` devolve o assento na passagem de `confirmed` para `cancelled`; outra
chamada para a reserva cancelada retorna o estado com `ja_cancelada=true`, sem alterar o banco.

Os históricos privados ficam na instância compilada do grafo, indexados por `tarefa_id`, fora do
estado do pai. Um checkpointer não os salva, e o Studio mostra só o estado do pai. O histórico de
uma tarefa é descartado em `termination`; uma execução interrompida por exceção do LangGraph,
como `GraphRecursionError`, não passa por `termination`.

`RunResult` contém `before`, `after`, `trace`, `final`, `values`, `error`, `seconds`, `eventos` e
`bitacora`. `--json` imprime esses campos. `bitacora` contém os handoffs; `eventos` inclui
`agent_start`, `agent_end`, `handoff`, `tool_call`, `tool_result`, `termination` e `error`.
Cada chamada de ferramenta registra o agente e o `chamada_id`; a evidência da proposta deve
referenciar o id da chamada de busca.

Um fechamento sem relatório ou com mensagem vazia gera `relatorio_ausente`, evento `error` e
`motivo_terminacao=error`. O harness preenche `RunResult.error`, e o avaliador reprova R11.
O evento de erro conserva `motivo_original`, inclusive `max_rodadas` ou `limite_repropostas`.
O marcador `relatorio_ausente` também reprova R11 em traças históricas com `error=null`.

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
alvo da matriz verificam a ativação antes de declarar detecção.

## Defeitos semeados

`--defeito` é repetível; `TRAVEL_DEFEITOS=D1,D3` configura os mesmos ids. O padrão não habilita
nenhum. As intervenções estão no grafo e em `agents/mas/defects.py`; nenhum defeito altera o
prompt.

| Id | Efeito |
|---|---|
| D1 | Verificador devolve aprovação sem invocar o subgrafo ou consultar o item |
| D2 | pesquisa encaminha aprovação fabricada e salta a verificação |
| D3 | rejeição é encaminhada ao Reservador, que tenta criar a reserva mesmo assim |
| D4 | Coordenador perde user_id no Pedido ou troca a identidade na Ordem |
| D5 | Reservador recebe a proposta rejeitada anterior no lugar da proposta aprovada |
| D6 | após rejeição, pesquisa e verificação ignoram os limites de rodadas e repropostas |

D4 atua no Pedido e na Ordem, que levam o `user_id` de reservas e cancelamentos. O avaliador
compara a identidade encaminhada com a solicitação do caso. D6 fica sujeito ao watchdog externo do
harness: a suíte limita o LangGraph a `min(recursion_limit, max_rodadas + 6)`. Uma interrupção pelo
harness é falha de terminação, sem relatório de sucesso do Coordenador.

## Casos e avaliação

`evaluation/casos.py` contém solicitação, estado inicial, falhas e expectativas com origem em
`spec/mas.yaml`. Os oráculos comparam estado final, subsequência ordenada de hitos, proibições,
limites de ocorrências e expressões simples sobre a mensagem. `evaluation/checks.py` também
confere relações entre Ordem, Proposta, Veredito e a escrita observada, referências de evidência,
orçamento, titularidade, duplicação, recuperação e terminação. Cada resultado traz `regra_origem`.
Valores como `spec/mas.yaml#regras.R3` identificam o arquivo e o id lógico da regra no YAML.

A evidência da proposta é o identificador da busca. Esse id aparece no conteúdo de cada
ToolMessage como `evidencia`, junto de `resultado`, além do metadado `tool_call_id`. Os eventos
guardam o resultado original da operação. O Pesquisador busca sem teto de preço, e as opções
acima do orçamento chegam ao Verificador.

Os resultados possíveis são `pass`, `fail`, `no_evaluable` e `no_activado`. `pass^k` de um caso é
1 somente quando todas as k execuções passam. Casos não avaliáveis ou com falhas não ativadas
ficam fora da média e aparecem contados separadamente. Uma execução sem erro de Python pode
falhar no avaliador por violar uma expectativa. O comando `casos` devolve código 1 quando alguma
execução não passa; `validar` também aponta defeitos não detectados ou controles com falha.

C06 combina um voo disponível com um hotel inexistente e não admite escrita; o relatório nomeia
o hotel ausente e o preço do voo. C07 verifica três noites dentro do teto total;
C07B usa um teto menor que o total mais barato para detectar confusão entre preço por noite e
total. C12P exercita timeout persistente.
C14 admite recusa ou consulta adicional, com reserva somente quando houver evidência válida.

`validar` roda a referência k vezes em ambas as topologias, os alvos D1–D6 e controles C11.
Cada execução é salva assim que termina. O resumo marca defeito detectado somente quando há
ativação registrada e falha de uma regra pertinente ao defeito. Resultados abaixo de k/k ficam
registrados nas traças de cada execução.

## Testes e Studio

```bash
uv run pytest
uv run ruff check src tests_mas main.py reports/scripts
uv run langgraph dev
```

A suíte em `tests_mas/` usa modelos scriptados e ferramentas sobre SQLite, sem chamadas ao
provedor. O modelo scriptado responde aos quatro agentes por uma fila só, e cada teste fixa a
ordem das ativações.

| Arquivo | Cobertura |
|---|---|
| `test_mas.py` | contratos, isolamento dos históricos, permissões, rotas e limites |
| `test_combined.py` | C06: pesquisa parcial, fechamento normal e por limite, omissões |
| `test_recovery.py` | C03: revisão aprovada reserva só a alternativa |
| `test_defects.py` | ativação de D1–D6 e controles fora do alvo |
| `test_evaluation.py` | oráculos, `pass^k`, falhas injetadas, CLI de casos e reavaliação |
| `test_reporting.py` | `tanda.py` sem provedor; `resumo.py` e `ids.py` sobre traças sintéticas |
| `test_domain.py` | ids iniciais com lacunas, rollback de escritas e cancelamento repetido |
| `test_integrity.py` | preço efetivo em R3, cancelamento repetido em R6 e fechamento sem relatório |

A suíte cobre pesquisa corrigida sem busca anterior, rejeição seguida de revisão aprovada,
timeout persistente, encerramento após duas pesquisas e sequência reservar–listar–cancelar nas
duas topologias. C06 cobre disponibilidade parcial, fechamento normal e por limite, omissões
no relatório e detecção de reserva parcial indevida. Os testes locais antigos em `tests/`,
ignorados pelo Git, não entram na suíte MAS.

`langgraph.json` publica apenas `travel_mas`, com um ambiente novo por execução do Studio.
O estado de entrada tem `pedido_usuario` (texto). O estado do grafo pai não inclui os históricos
privados dos agentes. A interface do Studio pode exigir `LANGSMITH_API_KEY`;
`LANGSMITH_TRACING=false` desativa o envio de traces.

## Evidência com o modelo real

A matriz `validar --k 3 --jobs 3` rodou sobre o commit `5288f47`, sem alterações locais, com
`gpt-oss:120b` no Ollama Cloud. As traças, `summary.json` e `manifest.json` ficam fora do
repositório. O manifesto registra o commit, `codigo_modificado: false`, o SHA-256 de 51 arquivos
(`src/`, `spec/mas.yaml`, `pyproject.toml`, `uv.lock`) e o plano das 126 execuções; os hashes
coincidem com os arquivos de `5288f47`.

| Fase | Execuções | Resultado |
|---|---|---|
| referência | 96: 16 casos, k=3, duas topologias | 31 de 32 combinações com 3/3 |
| defeitos-alvo | 18: D1–D6 nos casos de `ALVOS` | D1–D6 detectados em workflow e em supervisor |
| controles C11 | 12: um por defeito e topologia | 12 de 12 aprovadas, sem ativação do defeito |

A combinação abaixo de 3/3 é C06 supervisor, com 2 de 3. Na execução reprovada, o Verificador
recebeu `Internal Server Error` do Ollama Cloud após três tentativas. A execução terminou
sem escrita, com `motivo_terminacao=error` e um relatório do Coordenador que informa o voo FL-101
por 980 EUR e o hotel ausente; o avaliador reprova R11 quando há `RunResult.error`.

Nas execuções `defeito-*`, `fail` indica que o avaliador reprovou a execução com o defeito ativo,
e a detecção conta quando a falha cai em uma regra de `REGRAS_DETECCAO`. D1 é detectado em C03;
em C04, o Coordenador recusa a aprovação automática, e a execução passa em workflow e termina
como `no_activado` em supervisor. D6 termina com `GraphRecursionError` do watchdog do harness nas
duas topologias e é reprovado por R10 e R11.

### Chamadas ao modelo

As traças registram eventos e chamadas de ferramenta, e não as chamadas ao modelo. A contagem
desta seção deriva dos eventos das 126 traças de `mas-validation-v3`.

Cada ativação de um agente percorre `pensar`, `executar` e `concluir` (`agents/mas/agent.py`).
`pensar` chama o modelo uma vez por rodada de ferramentas e uma vez para a resposta final, e
`concluir` faz mais uma chamada para preencher o contrato por `function_calling`. Uma ativação
sem ferramenta faz duas chamadas; uma ativação com `n` chamadas de ferramenta faz de três a
`n + 2`, conforme o modelo agrupe as chamadas em uma rodada ou em rodadas separadas. Em
`supervisor`, o Coordenador é ativado depois de cada agente para preencher `Decisao`. Em C01, a
sequência de ativações, com as chamadas de ferramenta entre parênteses, foi:

```
workflow:
  coordenador → pesquisador(1) → verificador(1) → coordenador → reservador(3) → coordenador
supervisor:
  coordenador → pesquisador(1) → coordenador → verificador(1) → coordenador → reservador(3)
  → coordenador
```

A execução de C01 corresponde a 15–17 chamadas ao modelo em workflow e a 17–19 em supervisor.
Por fase, as 126 execuções de v3 somam:

| Fase | Execuções | Ativações | Chamadas de ferramenta | Chamadas ao modelo |
|---|---|---|---|---|
| referência | 96 | 500 | 349 | 1223–1349 |
| defeitos-alvo | 18 | 135 | 64 | 323–334 |
| controles C11 | 12 | 12 | 0 | 24 |
| total | 126 | 647 | 413 | 1570–1707 |

Na fase de referência, a média é de 4,9 ativações por execução em workflow e 5,5 em supervisor,
e de 12,7 a 14,1 chamadas ao modelo por execução. Uma tanda de seis execuções de referência
corresponde a 76–84 chamadas. A contagem não inclui as tentativas de `with_transient_retry` após
erro do provedor nem as de `preencher` após saída inválida, que os eventos não registram.

`reports/scripts/` lê as traças sem executar agentes: `resumo.py` imprime status e checks com
falha e ignora `summary.json` e `manifest.json`, `eventos.py` imprime a sequência de handoffs e
chamadas, e `ids.py` conta formatos de `item_id` nos diretórios recebidos ou, sem argumentos,
nos subdiretórios do diretório atual.
`tanda.py` imprime o plano de uma tanda; a execução com o provedor exige `--autorizar-provedor`,
admite até seis execuções e recusa um diretório existente.

```bash
uv run --offline python reports/scripts/resumo.py reports/mas-validation-v3/*.json
uv run --offline python reports/scripts/ids.py reports/mas-validation-v3
uv run --offline python reports/scripts/tanda.py reports/nova-tanda --casos C06 --k 3
```

## Verificação de integridade

A suíte tem 119 testes locais sem provedor. `test_domain.py` e `test_integrity.py` cobrem
transações, ids não contíguos, cancelamento repetido no domínio e em R6, orçamento total e
fechamento sem relatório. Em R3, o avaliador usa o preço da reserva criada, correlacionando o
resultado da ferramenta com a linha guardada; quando não há escrita observável, mantém o preço
informado na chamada.

`reports/scripts/reavaliar_integridade.py` compara o avaliador de um commit com o atual sobre as
mesmas traças e os casos vigentes, sem executar agentes. `--baseline` exige o commit do avaliador
de comparação. A saída registra, por diretório, os status antes e depois, os checks alterados
e os hashes das fontes e das traças lidas. O script exige um arquivo de saída novo e não altera
as traças.

```bash
uv run --offline python reports/scripts/reavaliar_integridade.py reports/mas-validation-v3 \
  --baseline HEAD --output reports/nova-revisao/summary.json
```

## Referências de implementação

- [Subgrafos e históricos privados](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#call-a-subgraph-inside-a-node).
- [Command e rotas](https://docs.langchain.com/oss/python/langgraph/graph-api#command).
- [Saída estruturada de modelos](https://docs.langchain.com/oss/python/langchain/models#structured-output).

No Ollama Cloud, o esquema é declarado como ferramenta por `function_calling` sobre a cópia do
cliente com `reasoning=False`. `runtime/structured.py` mantém até três tentativas de preencher
um esquema válido; texto livre ou resposta sem a chamada ao esquema não são aceitos.
