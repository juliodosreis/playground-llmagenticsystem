# Agente de reservas de viagem

Agente em LangGraph que busca e reserva voos e hotéis de um catálogo em SQLite. O pacote traz as
ferramentas que escrevem no banco, uma CLI de cenários e a suíte de testes.

## 1. Ambiente

O catálogo tem quatro voos e três hotéis, semeados em memória a cada execução. O estado mutável
são as reservas em `bookings` e a coluna `flights.seats`.

`create_booking` insere a reserva e decrementa o assento. `cancel_booking` marca a linha como
`cancelled` e devolve o assento. Um item fora do catálogo, um voo sem assento livre ou um `kind`
diferente de `flight` e `hotel` devolvem erro sem alterar o banco.

## 2. Estrutura

```
src/travel_mas/
    domain/             catálogo, banco e regras de reserva, sem LangChain
        catalog.py      esquema SQL, voos, hotéis, tabelas mutáveis
        database.py     TravelDB em memória, snapshot, hash e diff do estado
        operations.py   busca, criação, consulta e cancelamento
    runtime/            infraestrutura comum a qualquer agente
        context.py      provedor, modelo, limites do laço
        models.py       carga do cliente de chat
        workspace.py    banco e trace de uma execução
        runner.py       execução sobre banco limpo, com trace e snapshots
        messages.py     leitura das mensagens que o grafo devolve
        display.py      trajetória e tabelas em texto
    tools/              as ferramentas ligadas a um workspace
        search.py       as duas buscas de catálogo
        bookings.py     criação, consulta e cancelamento
    agents/             um pacote por agente
        travel/
            prompts.py  prompt de sistema
            tools.py    as ferramentas que este agente recebe
            state.py    estado do grafo: messages e passos
            graph.py    laço de ferramentas como StateGraph
    evaluation/         comparação de modelos, que nenhum agente importa
        compare.py      execução dos cenários por vários modelos
        report.py       tabela do relatório
    scenarios.py        os pedidos de demonstração
    cli.py              comandos
tests/                  domínio, ferramentas, grafo, provedores, comparação e CLI
```

`agents/<nome>/tools.py` nomeia as ferramentas do agente, e `Toolbox.select()` troca cada nome
pelo objeto correspondente. Um nome que não esteja no `Toolbox` levanta `KeyError` na montagem
do grafo.

## 3. Instalação

```bash
conda activate agents
pip install -e ".[dev]"
```

Sem instalar o pacote, `python main.py <comando>` acrescenta `src/` ao caminho de importação.

Chave de API: copie `.env.example` para `.env` e preencha `OLLAMA_API_KEY`, gerada em
[ollama.com/settings/keys](https://ollama.com/settings/keys). O `.env` não é versionado. O
provedor Google pede `pip install -e ".[google]"` e a chave `GOOGLE_API_KEY`, gerada em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). O Studio roda com
`pip install -e ".[studio]"` e pede `LANGSMITH_API_KEY`, gerada em
[smith.langchain.com/settings](https://smith.langchain.com/settings).

## 4. Execução

```bash
python -m travel_mas catalogo          # voos e hotéis do ambiente
python -m travel_mas cenarios          # lista os seis cenários
python -m travel_mas demo              # roda todos
python -m travel_mas demo 2 3          # roda os cenários 2 e 3
python -m travel_mas run "Reserve o voo MAD-LIM de 2026-09-12 por até 1000 EUR. Sou u-42."
python -m travel_mas comparar --modelo ollama --modelo google   # dois modelos lado a lado
```

Opções: `--provider ollama|google`, `--model <id>`, `--max-steps <n>`, `--json`.

```bash
python -m travel_mas --provider google demo 1          # gemini-3.5-flash-lite
python -m travel_mas --provider google --model gemini-2.5-flash demo 1
```

Sem `--model` nem `TRAVEL_MODEL`, cada provedor usa o modelo de `DEFAULT_MODELS`: `gpt-oss:120b`
no Ollama e `gemini-3.5-flash-lite` no Google. `gemini` é aceito como nome do provedor Google. Os
parâmetros de amostragem que cada família aceita ficam em `runtime/models.py`.

Cada execução parte de um banco limpo e imprime a trajetória de chamadas, a tabela `bookings`
resultante, os assentos consumidos e a mensagem final.

### 4.1 Cenários

| # | Nome | Pedido |
|---|---|---|
| 1 | `voo-orcamento` | um voo, com duas opções na data e uma acima do teto de preço |
| 2 | `voo-e-hotel` | voo e hotel no mesmo pedido, com um teto para cada |
| 3 | `sem-disponibilidade` | uma data sem voo no catálogo |
| 4 | `fora-do-orcamento` | uma data com voo, e teto abaixo do preço da opção mais barata |
| 5 | `reserva-e-cancelamento` | reservar, listar e cancelar |
| 6 | `consulta-vazia` | um usuário sem reservas |

Os cenários 3 e 4 terminam sem escrita e por caminhos diferentes. A busca filtra o preço em SQL,
então um teto abaixo de toda a oferta devolve lista vazia, igual a uma data sem voo. O prompt
manda repetir a busca sem o teto: no cenário 3 a segunda busca também vem vazia, e no 4 devolve
FL-101 e FL-102, o que permite responder que o mais barato custa 980 EUR e passa do orçamento.

Os tempos, as trajetórias e os desvios observados nas execuções dos dois modelos estão em
[MEDICOES.md](MEDICOES.md).

### 4.2 Comparação de modelos

```bash
python -m travel_mas comparar --modelo ollama --modelo google
python -m travel_mas comparar --modelo ollama:gpt-oss:20b --modelo google 2 5
```

`--modelo` aceita `provedor` ou `provedor:modelo`, e se repete uma vez por modelo. A divisão
ocorre no primeiro dois-pontos, então `ollama:gpt-oss:20b` mantém o identificador inteiro. Sem
modelo, vale o padrão do provedor. Dois specs que resolvem para o mesmo modelo são recusados.

O relatório traz uma linha por cenário e uma coluna por modelo, com o tempo e o número de chamadas
de ferramenta, e a coluna `estado`:

```
  cenário                    gpt-oss:120b  gemini-3.5-flash-lite  estado
  -------------------------  ------------  ---------------------  ------
  1. voo-orcamento           2.8s / 3      4.0s / 3               igual
  2. voo-e-hotel             9.5s / 8      3.4s / 6               difere
```

`estado` compara o `state_hash` do banco no fim de cada execução. Dois modelos com o mesmo hash
deixaram o banco igual, por trajetórias que podem ter sido diferentes. Os cenários que divergem
saem listados com o hash de cada modelo. Um modelo cujo grafo não monta, por chave de API ausente,
ocupa a coluna com `erro` e os demais continuam.

### 4.3 LangGraph Studio

```bash
langgraph dev
```

O comando sobe a API em `http://127.0.0.1:2024` e imprime o endereço do Studio, em
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`. O grafo roda na máquina
local, e a interface é uma página servida pelo LangSmith, que pede conta e `LANGSMITH_API_KEY` no
`.env`. Com `LANGSMITH_TRACING=false`, as execuções não são enviadas ao LangSmith.

`langgraph.json` aponta para `make_graph`, que monta o grafo sobre um workspace novo. O servidor
chama o montador no laço de eventos, e `Workspace()` abre SQLite de forma sincrônica, então
`make_graph` é assíncrona e passa a montagem a um thread com `asyncio.to_thread`. A chamada ao
montador se repete a cada requisição, e cada execução do Studio parte de um banco sem reservas.

O servidor guarda threads, checkpoints e store em `.langgraph_api/`, que o `.gitignore` cobre.
Apagar o diretório com o servidor parado descarta o histórico de threads do Studio, e o arranque
seguinte recria os arquivos:

```bash
rm -rf .langgraph_api/
```

## 5. Estado da execução

`TravelDB.snapshot()` devolve as tabelas mutáveis em ordem fixa, `state_hash()` reduz um
snapshot a 16 caracteres, e `diff_state()` lista as linhas acrescentadas, removidas e alteradas
entre dois snapshots.

`Workspace` reúne o banco e o trace de uma execução. `Workspace.reset()` troca o banco por um
limpo, e as ferramentas continuam ligadas ao mesmo objeto, então um grafo compilado roda vários
cenários sem herdar estado do anterior.

`arun_task` devolve `RunResult`, com os dois snapshots, o trace, a mensagem final, o tempo em
segundos e o campo `error` preenchido quando o agente levanta exceção. `run_task` é o envoltório
sincrônico, e as execuções de um processo compartilham um laço de eventos só. Dentro de um laço
já em execução, como uma célula de notebook, use `await arun_task(...)`.

## 6. Ferramentas

| Ferramenta | Efeito |
|---|---|
| `search_flights`, `search_hotels` | leem o catálogo |
| `create_booking` | insere a reserva e decrementa o assento |
| `get_booking`, `list_bookings` | leem o estado mutável |
| `cancel_booking` | marca `cancelled` e devolve o assento |

A regra de cada uma fica em `domain/operations.py` e não importa LangChain. O pacote `tools/`
fixa o banco da execução, grava a chamada no trace e agrupa as ferramentas em `CATALOG_TOOLS`,
`BOOKING_READ_TOOLS` e `BOOKING_WRITE_TOOLS`.

Um erro de execução volta como dado (`{"error": "flight_not_found"}`) e chega ao modelo como
`ToolMessage`.

O preço sai das ferramentas sem unidade, e o prompt declara que o catálogo está em EUR.

`with_transient_retry` envolve o modelo já com as ferramentas ligadas e reintenta os erros
passageiros do provedor, com `Context.retry_attempts` tentativas e espera exponencial. Esgotadas
as tentativas, o erro entra em `RunResult.error` e a suíte de cenários continua.

## 7. Grafo

```
START -> chamar_modelo -> decidir_proximo_no
                             |-- há pedidos e passos < max_steps -> executar_ferramentas
                             |                                            |
                             |                                            +-> chamar_modelo
                             +-- caso contrário --------------------------------> END
```

O estado tem `messages`, com o reducer `add_messages`, e `passos`, escrito pelo nó do modelo e
lido pela rota. Ao atingir `max_steps`, a rota encerra o laço e a mensagem final sai vazia. O nó
de ferramentas é um `ToolNode`.

## 8. Testes

```bash
pytest
```

46 testes, nenhum deles chama um provedor. `tests/fakes.py` traz um modelo de chat que devolve
respostas fixas, incluindo pedidos de chamada de ferramenta.

| Arquivo | Testes | Cobertura |
|---|---|---|
| `test_domain.py` | 12 | regras de reserva, sequência de ids, `state_hash` e `diff_state` |
| `test_graph.py` | 9 | laço de ferramentas, `max_steps`, isolamento, laço de eventos, reintento |
| `test_runtime.py` | 7 | modelo padrão por provedor, parâmetros do Gemini 3, provedor recusado |
| `test_tools.py` | 7 | registro das seis ferramentas, schema pela assinatura, trace e `reset()` |
| `test_evaluation.py` | 7 | leitura do spec, estado igual e diferente, falha de montagem |
| `test_cli.py` | 4 | comandos que dispensam chave de API |

`test_runtime.py` monta o cliente do Google com uma chave falsa e lê os parâmetros do objeto, sem
chamar a API.

## 9. Camadas não implementadas

- multiagente: `agents/researcher/` com as buscas, `agents/booker/` com a escrita,
  `agents/reviewer/` com leitura e cancelamento, e `agents/supervisor/`, que os chama como
  ferramentas;
- avaliação: `evaluation/` compara modelos entre si. Falta o estado final contra um golden state,
  a trajetória contra uma referência e o juiz LLM sobre a mensagem final.

## 10. Referências

- LangGraph: https://docs.langchain.com/oss/python/langgraph/overview
- Ferramentas no LangChain: https://docs.langchain.com/oss/python/langchain/tools
- Padrões multiagente: https://docs.langchain.com/oss/python/langchain/multi-agent/index
- Subagents: https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- Ollama Cloud: https://docs.ollama.com/cloud
