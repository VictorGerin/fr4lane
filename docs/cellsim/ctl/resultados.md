# Simulação analógica das células — `discrete_ctl`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, rápido, quente.

## Combinacionais e latches

| Célula | típico | lento | rápido | quente |
|---|---|---|---|---|
| AND2 | OK, tpd 531 ns | OK, tpd 417 ns | OK, tpd 702 ns | OK, tpd 471 ns |
| BUF | OK, tpd 556 ns | OK, tpd 465 ns | OK, tpd 700 ns | OK, tpd 561 ns |
| DLAT | OK, tpd 1.1 µs | OK, tpd 908 ns | OK, tpd 1.35 µs | OK, tpd 996 ns |
| INV | OK, tpd 418 ns | OK, tpd 316 ns | OK, tpd 610 ns | OK, tpd 382 ns |
| NAND2 | OK, tpd 308 ns | OK, tpd 188 ns | OK, tpd 470 ns | OK, tpd 268 ns |
| NOR2 | OK, tpd 658 ns | OK, tpd 476 ns | OK, tpd 890 ns | OK, tpd 542 ns |
| NOR3 | OK, tpd 622 ns | OK, tpd 464 ns | OK, tpd 812 ns | OK, tpd 520 ns |
| OR2 | OK, tpd 796 ns | OK, tpd 625 ns | OK, tpd 980 ns | OK, tpd 721 ns |
| XNOR2 | OK, tpd 1.11 µs | OK, tpd 869 ns | OK, tpd 1.38 µs | OK, tpd 998 ns |
| XOR2 | OK, tpd 670 ns | OK, tpd 566 ns | OK, tpd 753 ns | OK, tpd 606 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 689 ns a 1.12 µs | 5 µs | 10 ns a 20 ns | 20 ns a 50 ns |
| DFF | lento | OK | 581 ns a 892 ns | 5 µs | 20 ns a 50 ns | < 10 ns |
| DFF | rápido | OK | 809 ns a 1.39 µs | 5 µs | 20 ns a 50 ns | 50 ns a 100 ns |
| DFF | quente | OK | 672 ns a 1.05 µs | 5 µs | 20 ns a 50 ns | < 10 ns |
| DFFR | típico | OK | 689 ns a 1.07 µs | 5 µs | 50 ns a 100 ns | 20 ns a 50 ns |
| DFFR | lento | OK | 581 ns a 867 ns | 5 µs | 50 ns a 100 ns | < 10 ns |
| DFFR | rápido | OK | 810 ns a 1.29 µs | 5 µs | 100 ns a 200 ns | 50 ns a 100 ns |
| DFFR | quente | OK | 673 ns a 1.02 µs | 5 µs | 50 ns a 100 ns | < 10 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
