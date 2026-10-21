# Circuito `tanque` na família `cmos` (ngspice)

21 células, 152 componentes, 17 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 17 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 246 ns (bomba no vetor 2) |
| lento | OK | — | 350 ns (bomba no vetor 2) |
| rápido | OK | — | 104 ns (bomba no vetor 2) |

Dados completos de todos os vetores e cantos em [tanque.csv](tanque.csv). Reproduzir (canto típico): `ngspice -b tanque.cir`

![tanque](tanque.png)

