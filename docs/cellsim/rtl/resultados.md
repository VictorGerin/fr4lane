# Simulação analógica das células — `discrete_rtl`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, rápido, quente.

## Combinacionais e latches

| Célula | típico | lento | rápido | quente |
|---|---|---|---|---|
| AND2 | OK, tpd 547 ns | OK, tpd 699 ns | OK, tpd 506 ns | OK, tpd 558 ns |
| AND2_X2 | OK, tpd 533 ns | OK, tpd 668 ns | OK, tpd 496 ns | OK, tpd 542 ns |
| BUF | OK, tpd 402 ns | OK, tpd 473 ns | OK, tpd 382 ns | OK, tpd 414 ns |
| DLAT | OK, tpd 616 ns | OK, tpd 680 ns | OK, tpd 636 ns | OK, tpd 653 ns |
| INV | OK, tpd 237 ns | OK, tpd 300 ns | OK, tpd 212 ns | OK, tpd 236 ns |
| NAND2 | OK, tpd 347 ns | OK, com aviso, tpd 465 ns | OK, tpd 299 ns | OK, tpd 336 ns |
| NOR2 | OK, tpd 238 ns | OK, tpd 301 ns | OK, tpd 213 ns | OK, tpd 237 ns |
| NOR3 | OK, tpd 239 ns | OK, tpd 303 ns | OK, tpd 214 ns | OK, tpd 238 ns |
| PULLUP | OK, tpd — | OK, tpd — | OK, tpd — | OK, tpd — |
| TBUF | OK, tpd 323 ns | OK, tpd 462 ns | OK, tpd 285 ns | OK, tpd 331 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 516 ns a 618 ns | 2 µs | 200 ns a 300 ns | < 10 ns |
| DFF | lento | OK | 595 ns a 680 ns | 2 µs | 300 ns a 500 ns | < 10 ns |
| DFF | rápido | OK | 510 ns a 638 ns | 2 µs | 200 ns a 300 ns | < 10 ns |
| DFF | quente | OK | 541 ns a 655 ns | 2 µs | 200 ns a 300 ns | < 10 ns |
| DFFR | típico | OK | 516 ns a 619 ns | 2 µs | 200 ns a 300 ns | < 10 ns |
| DFFR | lento | OK | 595 ns a 681 ns | 2 µs | 300 ns a 500 ns | < 10 ns |
| DFFR | rápido | OK | 510 ns a 639 ns | 2 µs | 200 ns a 300 ns | < 10 ns |
| DFFR | quente | OK | 542 ns a 656 ns | 2 µs | 200 ns a 300 ns | < 10 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.

## Problemas e avisos

- NAND2 (lento): Y = 0.59 V com A=1 B=1: fora da faixa (esperado 0), mas a carga ainda entende 0
