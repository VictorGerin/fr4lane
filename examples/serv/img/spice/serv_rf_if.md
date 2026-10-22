# Circuito `serv_rf_if` na família `rtl` (ngspice)

9 células, 53 componentes, 16 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 16 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | 27 % | 539 ns (o_wen0 no vetor 1) |
| lento | OK | 27 % | 694 ns (o_wen0 no vetor 1) |
| rápido | OK | 27 % | 493 ns (o_wen0 no vetor 1) |
| quente | OK | 27 % | 541 ns (o_wen0 no vetor 1) |

Dados completos de todos os vetores e cantos em [serv_rf_if.csv](serv_rf_if.csv). Reproduzir (canto típico): `ngspice -b serv_rf_if.cir`

![serv_rf_if](serv_rf_if.png)

