# Simulação analógica das células — `discrete_relay`

Gerado por `pcbflow-cellsim` (ngspice). Cantos: típico, lento, quente, rápido.

## Combinacionais e latches

| Célula | típico | lento | quente | rápido |
|---|---|---|---|---|
| AND2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| BUF | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| DLAT | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| INV | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| MUX2 | OK, tpd 5.03 ms | OK, tpd 5.04 ms | **falhou**, tpd 150 ms | OK, tpd 5.03 ms |
| NAND2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| NOR2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| OR2 | OK, tpd 5.04 ms | OK, tpd 5.04 ms | **falhou**, tpd — | OK, tpd 5.04 ms |
| XNOR2 | OK, tpd 5.03 ms | OK, tpd 5.03 ms | **falhou**, tpd — | OK, tpd 5.03 ms |
| XOR2 | OK, tpd 5.03 ms | OK, tpd 5.03 ms | **falhou**, tpd 50 ms | OK, tpd 5.03 ms |

## Flip-flops

| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |
|---|---|---|---|---|---|---|
| DFF | típico | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFF | lento | OK | 10 ms a 10 ms | 30 ms | 5 ms a 7 ms | < 500 µs |
| DFF | quente | **falhou** | — | — | > 20 ms | > 20 ms |
| DFF | rápido | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | típico | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |
| DFFR | lento | OK | 10 ms a 10 ms | 30 ms | 5 ms a 7 ms | < 500 µs |
| DFFR | quente | **falhou** | — | — | > 20 ms | > 20 ms |
| DFFR | rápido | OK | 10 ms a 10 ms | 30 ms | 3 ms a 5 ms | < 500 µs |

Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado ("< x": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o nível de pior caso, e a saída leva o fan-out máximo.

## Problemas e avisos

- AND2 (quente): Y = 0.00 V com A=1 B=1 (esperado 1); a carga ficou em 4.75 V
- BUF (quente): Y = 0.00 V com A=1 (esperado 1); a carga ficou em 4.75 V
- DFF (quente): captura errada com período de 100000 µs: Q = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], esperado [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0]
- DFFR (quente): captura errada com período de 100000 µs: Q = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], esperado [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0]
- DLAT (quente): Q = 0.0 V em 95000.0 µs (transparente; esperado 1)
- DLAT (quente): Q = 0.0 V em 195000.0 µs (transparente; esperado 1)
- DLAT (quente): Q = 0.0 V em 295000.0 µs (travado; esperado 1)
- DLAT (quente): Q = 0.0 V em 345000.0 µs (travado; esperado 1)
- INV (quente): Y = 4.73 V com A=1 (esperado 0); a carga ficou em 4.75 V
- MUX2 (quente): Y = 0.00 V com A=0 B=1 S=1 (esperado 1); a carga ficou em 4.75 V
- MUX2 (quente): Y = 4.73 V com A=1 B=0 S=1 (esperado 0); a carga ficou em 4.75 V
- NAND2 (quente): Y = 4.73 V com A=1 B=1 (esperado 0); a carga ficou em 4.75 V
- NOR2 (quente): Y = 4.71 V com A=0 B=1 (esperado 0); a carga ficou em 4.75 V
- NOR2 (quente): Y = 4.71 V com A=1 B=0 (esperado 0); a carga ficou em 4.75 V
- NOR2 (quente): Y = 4.71 V com A=1 B=1 (esperado 0); a carga ficou em 4.75 V
- OR2 (quente): Y = 0.00 V com A=0 B=1 (esperado 1); a carga ficou em 4.75 V
- OR2 (quente): Y = 0.00 V com A=1 B=0 (esperado 1); a carga ficou em 4.75 V
- OR2 (quente): Y = 0.00 V com A=1 B=1 (esperado 1); a carga ficou em 4.75 V
- XNOR2 (quente): Y = 4.71 V com A=0 B=1 (esperado 0); a carga ficou em 4.75 V
- XNOR2 (quente): Y = 4.71 V com A=1 B=0 (esperado 0); a carga ficou em 4.75 V
- XOR2 (quente): Y = 0.00 V com A=0 B=1 (esperado 1); a carga ficou em 4.75 V
- XOR2 (quente): Y = 4.73 V com A=1 B=1 (esperado 0); a carga ficou em 4.75 V
