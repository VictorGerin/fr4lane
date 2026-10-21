# Circuito `tanque` na família `dtl` (ngspice)

18 células, 292 componentes, 17 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 17 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 330 ns (bomba no vetor 6) |
| lento | OK | — | 294 ns (bomba no vetor 6) |
| rápido | OK | — | 385 ns (bomba no vetor 2) |
| quente | OK | — | 354 ns (bomba no vetor 6) |

Dados completos de todos os vetores e cantos em [tanque.csv](tanque.csv). Reproduzir (canto típico): `ngspice -b tanque.cir`

![tanque](tanque.png)

