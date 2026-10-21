# Circuito `tanque` na família `tube` (ngspice)

19 células, 188 componentes, 17 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 17 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 1.69 µs (bomba no vetor 2) |
| lento | OK | — | 1.76 µs (bomba no vetor 2) |
| rápido | OK | — | 1.62 µs (bomba no vetor 2) |
| quente | OK | — | 1.75 µs (bomba no vetor 2) |

Dados completos de todos os vetores e cantos em [tanque.csv](tanque.csv). Reproduzir (canto típico): `ngspice -b tanque.cir`

![tanque](tanque.png)

