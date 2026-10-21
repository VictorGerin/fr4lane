# Simulação analógica das células — `discrete_tube`

Gerado por `fr4lane-cellsim` (ngspice). Cantos: típico, lento, rápido, quente.

## Combinacionais e latches

| Célula | típico | lento | rápido | quente |
|---|---|---|---|---|
| AND2 | OK, tpd 582 ns | OK, tpd 613 ns | OK, tpd 554 ns | OK, tpd 609 ns |
| BUF | OK, tpd 603 ns | OK, tpd 611 ns | OK, tpd 590 ns | OK, tpd 601 ns |
| DLAT | OK, tpd 1.08 µs | OK, tpd 1.11 µs | OK, tpd 1.04 µs | OK, tpd 1.1 µs |
| INV | OK, tpd 367 ns | OK, tpd 358 ns | OK, tpd 371 ns | OK, tpd 349 ns |
| NAND2 | OK, tpd 251 ns | OK, tpd 268 ns | OK, tpd 253 ns | OK, tpd 269 ns |
| NOR2 | OK, tpd 390 ns | OK, tpd 380 ns | OK, tpd 396 ns | OK, tpd 370 ns |
| NOR3 | OK, tpd 401 ns | OK, tpd 390 ns | OK, tpd 408 ns | OK, tpd 380 ns |
| OR2 | OK, tpd 631 ns | OK, tpd 638 ns | OK, tpd 619 ns | OK, tpd 627 ns |
| XNOR2 | OK, tpd 745 ns | OK, tpd 777 ns | OK, tpd 713 ns | OK, tpd 772 ns |
| XOR2 | OK, tpd 772 ns | OK, tpd 817 ns | OK, tpd 730 ns | OK, tpd 813 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 736 ns a 1.09 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFF | lento | OK | 775 ns a 1.13 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFF | rápido | OK | 699 ns a 1.05 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFF | quente | OK | 770 ns a 1.12 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFFR | típico | OK | 738 ns a 1.1 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFFR | lento | OK | 777 ns a 1.14 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFFR | rápido | OK | 702 ns a 1.06 µs | 5 µs | 100 ns a 200 ns | < 10 ns |
| DFFR | quente | OK | 772 ns a 1.13 µs | 5 µs | 100 ns a 200 ns | < 10 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
