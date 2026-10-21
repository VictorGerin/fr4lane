# Circuito `add4` na família `cmos` (ngspice)

36 células, 144 componentes, 512 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 64 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 521 ns (s[3] no vetor 469) |
| lento | OK | — | 791 ns (s[3] no vetor 469) |
| rápido | OK | — | 223 ns (s[3] no vetor 32) |

Dados completos de todos os vetores e cantos em [add4.csv](add4.csv). Reproduzir (canto típico): `ngspice -b add4.cir`

![add4](add4.png)

