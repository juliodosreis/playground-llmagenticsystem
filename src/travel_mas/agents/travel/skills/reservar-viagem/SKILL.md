---
name: reservar-viagem
description: >-
  Reserva de voos e hotéis: busca as opções, reserva a mais barata que cumpre a data e o
  orçamento do pedido e confirma o que ficou gravado. Aplica-se a todo pedido que peça para
  reservar um voo ou um hotel.
---

Fluxo de cada pedido:
1. Busque as opções com search_flights e search_hotels antes de afirmar qualquer preço ou disponibilidade.
2. Reserve com create_booking a opção mais barata que cumpra TODOS os requisitos do usuário: data pedida e teto de orçamento.
3. Confirme com get_booking o que ficou gravado e informe o booking_id ao usuário.
