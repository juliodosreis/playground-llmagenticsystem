# Agente de reservas de viagem

O agente recebe um pedido de viagem em texto, com origem, destino, data e orçamento, e resolve
esse pedido chamando ferramentas: procura voos e hotéis no catálogo, cria a reserva, lista as
reservas de um usuário e cancela. O catálogo e as reservas ficam em um banco SQLite, e as
ferramentas alteram esse banco, então uma reserva ocupa um assento do voo e um cancelamento o
devolve. Cada execução parte de um banco limpo e imprime as chamadas que o modelo fez, o estado
do banco no fim e a resposta ao pedido.

## 1. Ambiente

O banco é criado em memória a cada execução, com três tabelas:

| Tabela | Representa | Colunas |
|---|---|---|
| `flights` | os voos à venda | `origin`, `destination`, `date`, `price`, `airline`, `seats` |
| `hotels` | os hotéis à venda | `city`, `name`, `stars`, `price_per_night` |
| `bookings` | as reservas | `user_id`, `kind`, `item_id`, `start_date`, `price`, `status` |

`flights` e `hotels` são o catálogo, semeado com as linhas de `domain/catalog.py` e igual em toda
execução. `bookings` começa vazia e recebe uma linha por reserva que o agente criar.

| Voo | Trecho | Data | Preço (EUR) | Assentos | Companhia |
|---|---|---|---|---|---|
| `FL-101` | MAD-LIM | 2026-09-12 | 980 | 4 | Iberia |
| `FL-102` | MAD-LIM | 2026-09-12 | 1240 | 9 | LATAM |
| `FL-103` | MAD-LIM | 2026-09-13 | 760 | 2 | Air France |
| `FL-201` | LIM-MAD | 2026-09-20 | 890 | 6 | Iberia |

| Hotel | Cidade | Nome | Estrelas | Preço por noite (EUR) |
|---|---|---|---|---|
| `HT-1` | LIM | Miraflores Suites | 4 | 120 |
| `HT-2` | LIM | Barranco Hostal | 2 | 45 |
| `HT-3` | LIM | Surco Business | 3 | 58 |

O agente altera as linhas de `bookings` e a coluna `flights.seats`. `create_booking` insere a
reserva com `status` em `confirmed` e decrementa o assento, e `cancel_booking` marca a linha como
`cancelled` e devolve o assento. As duas tabelas formam o snapshot que `state_hash` resume, e uma
execução que não escreva deixa o hash do início.

Quatro erros de reserva voltam sem alterar o banco: `flight_not_found` e `hotel_not_found` para
um `item_id` fora do catálogo, `no_seats_available` para um voo sem assento livre, e
`invalid_kind` para um `kind` diferente de `flight` e `hotel`.

## 2. Estrutura

```
src/travel_mas/
    domain/             catálogo, banco e regras de reserva
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
    evaluation/         comparação de modelos
        compare.py      execução dos cenários por vários modelos
        report.py       tabela do relatório
    scenarios.py        os pedidos de demonstração
    cli.py              comandos
```

`agents/<nome>/tools.py` nomeia as ferramentas do agente, e `Toolbox.select()` troca cada nome
pelo objeto correspondente. Um nome que não esteja no `Toolbox` levanta `KeyError` na montagem
do grafo.

## 3. Instalação

O `uv` gerencia o interpretador, o ambiente e as dependências. O instalador está em
[docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`uv sync` lê `pyproject.toml` e `uv.lock`, cria `.venv/` na raiz do repositório e instala as
dependências, o pacote em modo editável e o grupo `dev`, com `pytest`, `ruff` e a CLI do
LangGraph. `.python-version` fixa o interpretador em 3.12, que o `uv` baixa quando não está na
máquina:

```bash
uv sync
```

Chave de API: copie `.env.example` para `.env` e preencha `OLLAMA_API_KEY`, gerada em
[ollama.com/settings/keys](https://ollama.com/settings/keys). O `.env` não é versionado, e o
`.env.example` traz o nome de cada variável do ambiente:

```bash
cp .env.example .env
```

O provedor Google fica em um extra, fora do conjunto padrão, e pede a chave `GOOGLE_API_KEY`,
gerada em [aistudio.google.com/apikey](https://aistudio.google.com/apikey). O Studio pede
`LANGSMITH_API_KEY`, gerada em
[smith.langchain.com/settings](https://smith.langchain.com/settings), e a CLI que o sobe está no
grupo `dev`:

```bash
uv sync --extra google
```

Uma chave exportada no terminal antes da execução tem precedência sobre o valor do `.env`, e
vale só na sessão do shell em que foi definida:

```bash
export OLLAMA_API_KEY=<chave>
```

`uv run` executa um comando no ambiente do projeto sem ativação prévia. A sincronização do
`.venv/` ocorre antes da execução, quando `pyproject.toml` ou `uv.lock` mudaram:

```bash
uv run python -m travel_mas catalogo
uv run pytest
```

A ativação do ambiente põe `python` e `travel-mas` no `PATH` da sessão. Os comandos das
seções seguintes dispensam o prefixo `uv run` a partir daí:

```bash
source .venv/bin/activate
```

Sem instalar o pacote, `python main.py <comando>` acrescenta `src/` ao caminho de importação.

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

A saída traz a trajetória de chamadas, a tabela `bookings` resultante, os assentos consumidos e a
mensagem final.

### 4.1 Cenários

| # | Nome | Pedido |
|---|---|---|
| 1 | `voo-orcamento` | um voo, com duas opções na data e uma acima do teto de preço |
| 2 | `voo-e-hotel` | voo e hotel no mesmo pedido, com um teto para cada |
| 3 | `sem-disponibilidade` | uma data sem voo no catálogo |
| 4 | `fora-do-orcamento` | uma data com voo, e teto abaixo do preço da opção mais barata |
| 5 | `reserva-e-cancelamento` | reservar, listar e cancelar |
| 6 | `consulta-vazia` | um usuário sem reservas |

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

`langgraph.json` aponta para `make_graph`, que monta o grafo sobre um workspace novo. A chamada ao
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

Um erro de execução volta como dado (`{"error": "flight_not_found"}`) e chega ao modelo como
`ToolMessage`. Um erro passageiro do provedor consome até `Context.retry_attempts` tentativas, com
espera exponencial entre elas; esgotadas as tentativas, o erro entra em `RunResult.error` e os
cenários seguintes continuam.

## 7. Grafo

```mermaid
graph TD;
    __start__([__start__])
    chamar_modelo(chamar_modelo)
    executar_ferramentas(executar_ferramentas)
    __end__([__end__])
    __start__ --> chamar_modelo;
    chamar_modelo -. fim .-> __end__;
    chamar_modelo -. executar .-> executar_ferramentas;
    executar_ferramentas --> chamar_modelo;
```

As duas arestas tracejadas saem de `decidir_proximo_no`, que devolve `executar` enquanto a última
mensagem trouxer pedido de chamada e `passos` estiver abaixo de `max_steps`, e `fim` nos demais
casos. Ao atingir `max_steps`, a rota encerra o laço e a mensagem final sai vazia.

O estado tem `messages`, com o reducer `add_messages`, e `passos`, escrito pelo nó do modelo e
lido pela rota. O nó de ferramentas é um `ToolNode`.

## 8. Referências

- LangGraph: https://docs.langchain.com/oss/python/langgraph/overview
- Ferramentas no LangChain: https://docs.langchain.com/oss/python/langchain/tools
- Padrões multiagente: https://docs.langchain.com/oss/python/langchain/multi-agent/index
- Subagents: https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- Ollama Cloud: https://docs.ollama.com/cloud
