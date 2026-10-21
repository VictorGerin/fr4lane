# Simulação analógica das células — `discrete_relay`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, quente, rápido.

## Combinacionais e latches

| Célula | típico | lento | quente | rápido |
|---|---|---|---|---|
| AND2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| BUF | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| DLAT | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| INV | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| MUX2 | OK, tpd 5.03 ms | OK, tpd 5.04 ms | OK, tpd 5.03 ms | OK, tpd 5.03 ms |
| NAND2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| NOR2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| OR2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms | OK, tpd 5.04 ms |
| XNOR2 | OK, tpd 5.03 ms | OK, tpd 5.03 ms | OK, tpd 5.03 ms | OK, tpd 5.03 ms |
| XOR2 | OK, tpd 5.03 ms | OK, tpd 5.03 ms | OK, tpd 5.03 ms | OK, tpd 5.03 ms |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | lento | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | quente | OK | 10 ms a 10 ms | 30 ms | 5 ms a 7 ms | < 500 µs |
| DFF | rápido | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | típico | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | lento | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | quente | OK | 10 ms a 10 ms | 30 ms | 5 ms a 7 ms | < 500 µs |
| DFFR | rápido | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
