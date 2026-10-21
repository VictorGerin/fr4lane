# Simulação analógica das células — `discrete_relay`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, quente, rápido.

## Combinacionais e latches

| Célula | típico | lento | quente | rápido |
|---|---|---|---|---|
| AND2 | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.39 ms | OK, tpd 5.34 ms |
| BUF | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.34 ms |
| DLAT | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.34 ms |
| INV | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.35 ms |
| MUX2 | OK, tpd 4.87 ms | OK, tpd 5.05 ms | OK, tpd 5.4 ms | OK, tpd 4.69 ms |
| NAND2 | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.35 ms |
| NOR2 | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.33 ms |
| OR2 | OK, tpd 5.25 ms | OK, tpd 5.17 ms | OK, tpd 5.4 ms | OK, tpd 5.34 ms |
| XNOR2 | OK, tpd 4.86 ms | OK, tpd 5.03 ms | OK, tpd 5.4 ms | OK, tpd 4.64 ms |
| XOR2 | OK, tpd 4.86 ms | OK, tpd 5.03 ms | OK, tpd 5.4 ms | OK, tpd 4.69 ms |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 9.79 ms a 10.2 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | lento | OK | 10.1 ms a 10.2 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | quente | OK | 10.5 ms a 10.8 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | rápido | OK | 9.28 ms a 9.98 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | típico | OK | 9.64 ms a 10.1 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | lento | OK | 10.1 ms a 10.2 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | quente | OK | 10.5 ms a 10.8 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | rápido | OK | 9.28 ms a 9.99 ms | 30 ms | 3 ms a 5 ms | < 500 µs |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
