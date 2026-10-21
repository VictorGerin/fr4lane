# Simulação analógica das células — `discrete_cmos`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, rápido.

## Combinacionais e latches

| Célula | típico | lento | rápido |
|---|---|---|---|
| AOI21 | OK, tpd 180 ns | OK, tpd 302 ns | OK, tpd 114 ns |
| BUF | OK, tpd 74 ns | OK, tpd 113 ns | OK, tpd 44 ns |
| DLAT | OK, tpd 128 ns | OK, tpd 190 ns | OK, tpd 52 ns |
| INV | OK, tpd 81 ns | OK, tpd 136 ns | OK, tpd 51 ns |
| NAND2 | OK, tpd 61 ns | OK, tpd 73 ns | OK, tpd 26 ns |
| NAND3 | OK, tpd 94 ns | OK, tpd 113 ns | OK, tpd 31 ns |
| NOR2 | OK, tpd 184 ns | OK, tpd 308 ns | OK, tpd 117 ns |
| NOR3 | OK, tpd 308 ns | OK, tpd 518 ns | OK, tpd 192 ns |
| OAI21 | OK, tpd 82 ns | OK, tpd 137 ns | OK, tpd 52 ns |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 65 ns a 108 ns | 500 ns | < 0.5 ns | 20 ns a 50 ns |
| DFF | lento | OK | 91 ns a 149 ns | 500 ns | < 0.5 ns | 50 ns a 100 ns |
| DFF | rápido | OK | 29 ns a 45 ns | 200 ns | < 0.5 ns | 10 ns a 20 ns |
| DFFR | típico | OK | 88 ns a 114 ns | 500 ns | < 0.5 ns | 20 ns a 50 ns |
| DFFR | lento | OK | 122 ns a 158 ns | 500 ns | < 0.5 ns | 50 ns a 100 ns |
| DFFR | rápido | OK | 38 ns a 48 ns | 200 ns | < 0.5 ns | 10 ns a 20 ns |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.
