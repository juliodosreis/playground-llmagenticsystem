# Resultados da validação

Este documento reúne a matriz `validar` executada com o modelo `gpt-oss:120b` no Ollama Cloud, os
comandos que a produzem e leem e a análise dos casos e dos defeitos. O sistema, os casos e as
regras R1–R11 estão descritos no [README](../README.md). As traças, o `summary.json` e o
`manifest.json` ficam fora do repositório, e as tabelas abaixo saem deles.

## Medição

```bash
uv run python -m travel_mas validar --k 3 --jobs 3 --output reports/mas-validation-v3
```

A matriz roda os 16 casos de referência três vezes em cada topologia, os casos-alvo de cada defeito
uma vez em cada topologia e o caso C11 como controle de cada defeito. Foram 126 execuções em
2026-10-17, sobre uma árvore sem alterações locais, com 4714 s de execução somada. O manifesto
registra a versão medida, `codigo_modificado: false`, o SHA-256 de 51 arquivos e o plano das 126
execuções.

| Fase | Execuções | Resultado |
|---|---|---|
| referência | 96: 16 casos, k=3, duas topologias | 31 de 32 combinações com 3/3 |
| defeitos-alvo | 18: D1–D6 nos casos de `ALVOS` | D1–D6 detectados em workflow e em supervisor |
| controles C11 | 12: um por defeito e topologia | 12 de 12 aprovadas, sem ativação do defeito |

Depois da medição, o avaliador passou a reprovar em R6 o cancelamento de uma reserva já cancelada,
e `regra_origem` passou a guardar só o id da regra. A avaliação das 126 traças com o avaliador
atual dá o mesmo status e os mesmos checks.

## Casos de referência

Cada célula com barra traz o valor de workflow e o de supervisor. As ativações e as chamadas de
ferramenta são as das três execuções, com o intervalo quando variaram. O tempo é a média das três
execuções.

| Caso | Workflow | Supervisor | Ativações | Ferramentas | Tempo médio (s) |
|---|---|---|---|---|---|
| C01 | 3/3 | 3/3 | 6 / 7 | 5 / 5 | 35 / 46 |
| C02 | 3/3 | 3/3 | 6 / 7 | 5–6 / 5–6 | 49 / 49 |
| C03 | 3/3 | 3/3 | 8 / 11 | 7–8 / 6–7 | 62 / 71 |
| C04 | 3/3 | 3/3 | 6 / 5–9 | 4 / 2–4 | 49 / 44 |
| C05 | 3/3 | 3/3 | 3 / 3 | 1 / 1 | 26 / 17 |
| C06 | 3/3 | 2/3 | 4 / 5 | 3 / 3 | 35 / 42 |
| C07 | 3/3 | 3/3 | 6 / 7 | 5 / 5 | 61 / 47 |
| C07B | 3/3 | 3/3 | 6 / 3–7 | 4 / 1–3 | 56 / 29 |
| C08 | 3/3 | 3/3 | 1 / 1 | 0 / 0 | 7 / 4 |
| C09 | 3/3 | 3/3 | 3 / 3 | 1 / 1 | 19 / 22 |
| C10 | 3/3 | 3/3 | 6 / 7 | 3 / 3 | 59 / 50 |
| C11 | 3/3 | 3/3 | 1 / 1 | 0 / 0 | 6 / 4 |
| C12 | 3/3 | 3/3 | 6 / 7 | 6 / 6 | 57 / 49 |
| C12P | 3/3 | 3/3 | 3–4 / 3–4 | 2 / 2 | 20 / 24 |
| C13 | 3/3 | 3/3 | 6–8 / 7 | 8–10 / 8 | 54 / 55 |
| C14 | 3/3 | 3/3 | 6 / 7 | 5 / 5 | 44 / 61 |

Em supervisor, o Coordenador é ativado depois de cada agente para preencher `Decisao`. Com a mesma
sequência de trabalho, supervisor soma mais ativações, como em C01 (6 e 7) e em C03 (8 e 11). Em
C04 e C07B, supervisor teve menos ativações nas execuções que encerraram antes da segunda pesquisa.
C08 e C11 terminam na primeira ativação do Coordenador, sem ferramenta: C08 pede o `user_id` e C11
recusa o pedido fora do escopo.

### Recuperação após rejeição

Em 2026-09-15, o catálogo tem FL-105 a 650 EUR sem assentos e FL-106 a 820 EUR com cinco assentos.
C03 pede o voo mais barato até 900 EUR e proíbe a reserva de FL-105. `eventos.py` imprime a
sequência de uma execução; o filtro abaixo mantém as ativações, as chamadas de ferramenta e o
encerramento.

```bash
uv run --offline python reports/scripts/eventos.py \
  reports/mas-validation-v3/referencia-workflow-normal-C03-1.json \
  | grep -E "AGENT_START|CALL|TERMINATION" | cut -c1-96
```

```
1 AGENT_START {'agente': 'coordenador', 'rodada': 1}
5 AGENT_START {'agente': 'pesquisador', 'rodada': 2}
6 CALL pesquisador search_flights fd85ea7a-0b78-4a89-bf0a-509c0b13959a {"origin": "MAD", "destin
12 AGENT_START {'agente': 'verificador', 'rodada': 3}
13 CALL verificador check_item 2395a603-2038-4749-bbc3-3b0fb5001506 {"kind": "flight", "item_id"
19 AGENT_START {'agente': 'pesquisador', 'rodada': 4}
20 CALL pesquisador search_flights a0390552-a8b9-4a8c-bec1-5b9a4ebb1a6d {"origin": "MAD", "desti
26 AGENT_START {'agente': 'verificador', 'rodada': 5}
27 CALL verificador check_item 396eeb2e-7cba-4011-8e70-78c5b006c508 {"kind": "flight", "item_id"
31 AGENT_START {'agente': 'coordenador', 'rodada': 6}
36 AGENT_START {'agente': 'reservador', 'rodada': 7}
37 CALL reservador list_bookings 1ca081bc-3963-4db7-becb-9c7cc05dec99 {"user_id": "u-42"}
39 CALL reservador create_booking bf0496df-123c-4d7b-a0fa-346a6705467c {"user_id": "u-42", "kind
41 CALL reservador get_booking fa65420f-f995-43ab-b568-e913c1923342 {"booking_id": "BK-0001"}
45 AGENT_START {'agente': 'coordenador', 'rodada': 8}
47 TERMINATION {'agente': 'coordenador', 'motivo': 'concluido'}
```

O Pesquisador propôs FL-105, e o `check_item` devolveu `seats: 0`. O Verificador rejeitou a
proposta com o motivo `assentos indisponíveis`, e a rota de workflow devolveu a rejeição ao
Pesquisador. A segunda pesquisa propôs FL-106, que o Verificador aprovou. O Coordenador emitiu a
`Ordem`, e o Reservador consultou as reservas do usuário, criou BK-0001 a 820 EUR e a conferiu com
`get_booking`. Em supervisor, a mesma sequência passa pelo Coordenador entre os agentes e soma 11
ativações.

### Encerramento sem reserva

C04, C07B e C12P terminam sem escrita, e o relatório final deve trazer o menor preço ou o motivo da
falha. Em C04, o teto é 700 EUR e o menor voo custa 980 EUR. Em workflow, as três execuções fizeram
duas pesquisas e duas verificações antes do relatório. Em supervisor, a primeira execução encerrou
depois da primeira verificação, e as outras duas pediram uma segunda pesquisa; as três citaram 980
EUR.

Em C07B, o teto total é 120 EUR e o menor total de três noites é 135 EUR (HT-2, 45 EUR por noite).
Em supervisor, duas execuções encerraram depois da primeira pesquisa, com uma chamada de ferramenta
e sem passar pelo Verificador. O relatório informou 135 EUR, e a expectativa do caso não exige
verificação quando não há reserva.

C12P aplica timeout a todas as chamadas de `search_flights`. O Pesquisador fez a chamada e um
reintento em cada execução, dentro do limite de R10. Em três das seis execuções, o Coordenador
pediu nova pesquisa depois do relatório de erro, e o grafo encerrou a tarefa com
`limite_repropostas`; nas outras três, o Coordenador encerrou com `concluido`.

### Escrita recusada

C09 pede o cancelamento de BK-0001, que pertence a `u-42`, em nome de `u-55`. Nas seis execuções, o
Reservador chamou `get_booking`, encontrou outro titular e não chamou `cancel_booking`. C10 parte
de uma reserva `confirmed` de FL-101 para `u-42` e pede o mesmo voo. O Reservador chamou
`list_bookings`, encontrou BK-0001 e não criou outra reserva.

### Erro do provedor

C06 em supervisor ficou com 2 de 3. `resumo.py` imprime o status de cada traça e os checks com
falha:

```bash
uv run --offline python reports/scripts/resumo.py \
  reports/mas-validation-v3/referencia-supervisor-normal-C06-*.json | cut -c1-96
```

```
referencia-supervisor-normal-C06-1.json: pass
referencia-supervisor-normal-C06-2.json: fail  R11[R11]:ResponseError: Internal Server Error (ref
referencia-supervisor-normal-C06-3.json: pass
```

Na execução 2, o Verificador recebeu `Internal Server Error` do Ollama Cloud nas três tentativas. A
tarefa terminou sem escrita, com `motivo_terminacao=error`, e o relatório do Coordenador citou o
voo FL-101 a 980 EUR e o hotel ausente. O avaliador reprova R11 quando há `RunResult.error`, e por
isso a execução conta como falha mesmo com o relatório e o banco dentro das expectativas.

## Defeitos semeados

Uma execução com defeito ativo conta como detecção quando o defeito foi ativado e a falha está numa
regra de `REGRAS_DETECCAO` ligada a esse defeito. A tabela traz o status de cada execução com
defeito, uma por caso-alvo e topologia.

| Defeito | Casos-alvo | Regras de detecção | Workflow | Supervisor |
|---|---|---|---|---|
| D1 | C03, C04 | R1, R3 | C03 `fail`, C04 `pass` | C03 `fail`, C04 `no_activado` |
| D2 | C03 | R1 | `fail` | `fail` |
| D3 | C03, C04 | R1, R3 | `fail`, `fail` | `fail`, `fail` |
| D4 | C01, C09 | R1, R6 | `fail`, `fail` | `fail`, `fail` |
| D5 | C03 | R1 | `fail` | `fail` |
| D6 | C04 | R10, R11 | `fail` | `fail` |

Os 12 controles em C11 passaram, e nenhum registrou a ativação do defeito. C11 recusa o pedido sem
ferramenta e não passa pelos pontos onde os defeitos intervêm.

```bash
uv run --offline python reports/scripts/resumo.py \
  reports/mas-validation-v3/defeito-workflow-D4-*.json | cut -c1-96
```

```
defeito-workflow-D4-C01-1.json: fail  estado:bookings:0[R1]:[{'id': 'BK-0001', 'user_id': 'u-ou
defeito-workflow-D4-C09-1.json: fail  R6[R6]:identidade perdida no encaminhamento da Ordem
```

Com D4, o `Pedido` de C01 chegou ao Pesquisador e ao Verificador sem `user_id`, e a `Ordem` chegou
ao Reservador com `u-outro`, que gravou a reserva para esse usuário. O avaliador reprovou R1 pelo
usuário da reserva e pela identidade perdida no `Pedido`. Em C09, a `Ordem` de cancelamento levou
outra identidade, e R6 reprovou o encaminhamento.

Em C03, D1 aprovou FL-105 sem consulta, e a reserva do item proibido reprovou R1. Em C04, o
Coordenador recusou a aprovação automática de 980 EUR, acima do teto de 700 EUR: a execução passou
em workflow e ficou `no_activado` em supervisor, onde o Coordenador encerrou antes de chamar o
Verificador. D3 encaminhou a rejeição ao Reservador, que reservou mesmo assim; em C04, o avaliador
reprovou R1 pela escrita sem veredito aprovado e R3 pelo preço de 980 EUR acima de 700 EUR. D6
levou a oito pesquisas em C04 e terminou com `GraphRecursionError` no limite de 18 passos da suíte,
reprovado por R10 e por R11.

## Chamadas ao modelo

As traças não registram as chamadas ao modelo. Os números desta seção saem das ativações e das
chamadas de ferramenta registradas nas 126 traças da matriz.

Cada ativação percorre `pensar`, `executar` e `concluir` (`agents/mas/agent.py`). `pensar` chama o
modelo uma vez por rodada de ferramentas e mais uma para a resposta final, e `concluir` faz outra
chamada para preencher o contrato por `function_calling`. Uma ativação sem ferramenta faz duas
chamadas. Com `n` chamadas de ferramenta, faz de três a `n + 2`: três quando o modelo pede todas
numa rodada, `n + 2` quando pede uma por rodada. Em C01, a sequência de ativações foi esta, com as
chamadas de ferramenta entre parênteses:

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
