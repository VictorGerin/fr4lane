# Simulação analógica das células — `discrete_cdl`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, rápido, quente.

## Combinacionais e latches

| Célula | típico | lento | rápido | quente |
|---|---|---|---|---|
| AND2 | OK, tpd 62.7 ns | OK, tpd 53.9 ns | OK, tpd 61.7 ns | OK, tpd 63.8 ns |
| BUF | OK, tpd 162 ns | OK, tpd 164 ns | OK, tpd 199 ns | OK, tpd 165 ns |
| DLAT | OK, tpd 375 ns | OK, tpd 372 ns | OK, tpd 344 ns | OK, tpd 383 ns |
| INV | OK, tpd 122 ns | OK, tpd 128 ns | OK, tpd 119 ns | OK, tpd 132 ns |
| NAND2 | OK, tpd 186 ns | OK, tpd 186 ns | OK, tpd 190 ns | OK, tpd 200 ns |
| NOR2 | OK, tpd 126 ns | OK, tpd 129 ns | OK, tpd 121 ns | OK, tpd 133 ns |
| NOR3 | OK, tpd 125 ns | OK, tpd 130 ns | OK, tpd 123 ns | OK, tpd 136 ns |
| OR2 | OK, tpd 193 ns | OK, tpd 158 ns | OK, tpd 184 ns | OK, tpd 190 ns |
| XNOR2 | OK, tpd 224 ns | OK, tpd 241 ns | OK, tpd 265 ns | OK, tpd 233 ns |
| XOR2 | OK, tpd 318 ns | OK, tpd 325 ns | OK, tpd 290 ns | OK, tpd 347 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 246 ns a 389 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFF | lento | OK | 253 ns a 407 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFF | rápido | OK | 244 ns a 371 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFF | quente | OK | 256 ns a 401 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFFR | típico | OK | 251 ns a 386 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFFR | lento | OK | 257 ns a 407 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFFR | rápido | OK | 244 ns a 378 ns | 1 µs | 50 ns a 100 ns | < 10 ns |
| DFFR | quente | OK | 253 ns a 405 ns | 1 µs | 50 ns a 100 ns | < 10 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
