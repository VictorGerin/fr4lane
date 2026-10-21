# Simulação analógica das células — `discrete_dtl`

Gerado por `fr4lane-cellsim` (ngspice). Cantos: típico, lento, rápido, quente.

## Combinacionais e latches

| Célula | típico | lento | rápido | quente |
|---|---|---|---|---|
| AND2 | OK, tpd 143 ns | OK, tpd 112 ns | OK, tpd 184 ns | OK, tpd 154 ns |
| BUF | OK, tpd 142 ns | OK, tpd 112 ns | OK, tpd 184 ns | OK, tpd 152 ns |
| DLAT | OK, tpd 243 ns | OK, tpd 210 ns | OK, tpd 261 ns | OK, tpd 255 ns |
| INV | OK, tpd 112 ns | OK, tpd 74.2 ns | OK, tpd 155 ns | OK, tpd 118 ns |
| NAND2 | OK, tpd 112 ns | OK, tpd 73 ns | OK, tpd 155 ns | OK, tpd 117 ns |
| NAND3 | OK, tpd 109 ns | OK, tpd 72.3 ns | OK, tpd 155 ns | OK, tpd 119 ns |
| NOR2 | OK, tpd 161 ns | OK, tpd 167 ns | OK, tpd 246 ns | OK, tpd 161 ns |
| NOR3 | OK, tpd 167 ns | OK, tpd 169 ns | OK, tpd 251 ns | OK, tpd 164 ns |
| OR2 | OK, tpd 236 ns | OK, tpd 247 ns | OK, tpd 277 ns | OK, tpd 256 ns |
| XNOR2 | OK, tpd 265 ns | OK, tpd 211 ns | OK, tpd 317 ns | OK, tpd 285 ns |
| XOR2 | OK, tpd 156 ns | OK, tpd 149 ns | OK, tpd 183 ns | OK, tpd 164 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 148 ns a 152 ns | 500 ns | < 10 ns | 50 ns a 100 ns |
| DFF | lento | OK | 115 ns a 146 ns | 500 ns | < 10 ns | 50 ns a 100 ns |
| DFF | rápido | OK | 160 ns a 188 ns | 1 µs | < 10 ns | 100 ns a 200 ns |
| DFF | quente | OK | 157 ns a 160 ns | 500 ns | < 10 ns | 50 ns a 100 ns |
| DFFR | típico | OK | 148 ns a 151 ns | 500 ns | < 10 ns | 50 ns a 100 ns |
| DFFR | lento | OK | 116 ns a 146 ns | 500 ns | < 10 ns | 50 ns a 100 ns |
| DFFR | rápido | OK | 160 ns a 188 ns | 1 µs | < 10 ns | 100 ns a 200 ns |
| DFFR | quente | OK | 157 ns a 161 ns | 500 ns | < 10 ns | 50 ns a 100 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
